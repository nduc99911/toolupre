"""
ReupMaster Pro - Video Downloader Service
Supports: TikTok, Douyin, Facebook, Instagram, YouTube, and more via yt-dlp.

Uses subprocess.run in thread pool instead of asyncio subprocess
to avoid NotImplementedError on Windows Python 3.14.
"""
import os
import re
import json
import uuid
import asyncio
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app import database as db
from app.services.progress import video_progress

logger = logging.getLogger("reupmaster.downloader")

# Thread pool for running subprocess commands
_executor = ThreadPoolExecutor(max_workers=4)


def detect_platform(url: str) -> str:
    """Detect social media platform from URL."""
    url_lower = url.lower()
    if "tiktok.com" in url_lower or "vm.tiktok.com" in url_lower or "vt.tiktok.com" in url_lower:
        return "tiktok"
    elif "douyin.com" in url_lower:
        return "douyin"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
        return "facebook"
    elif "instagram.com" in url_lower:
        return "instagram"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "x.com" in url_lower or "twitter.com" in url_lower:
        return "twitter"
    else:
        return "other"


def get_ffmpeg_path() -> str:
    """Get FFmpeg path from settings or default."""
    return settings.FFMPEG_PATH if settings.FFMPEG_PATH else "ffmpeg"


def _run_command(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """
    Run a command synchronously (called from thread pool).
    Returns (returncode, stdout, stderr).
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            text=False,  # Get bytes
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        return result.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def _run_yt_dlp_sync(cmd: list[str], video_id: str, timeout: int = 300) -> tuple[int, str]:
    """Run yt-dlp synchronously, parse progress, update memory, returncode, full_output"""
    try:
        # Add newline argument for better progress parsing
        if "--newline" not in cmd:
            cmd.insert(1, "--newline")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        all_output = []
        for line in process.stdout:
            all_output.append(line)
            line_str = line.strip()

            # Parse yt-dlp progress
            if "[download]" in line_str and "%" in line_str:
                match = re.search(r'(\d+\.?\d*)%', line_str)
                if match:
                    video_progress[video_id] = float(match.group(1))

        process.wait(timeout=timeout)
        return process.returncode, "".join(all_output)
    except subprocess.TimeoutExpired:
        if process:
            process.kill()
        return -1, "".join(all_output) + "\ntimeout"
    except Exception as e:
        return -1, str(e)


async def _run_command_async(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run a command asynchronously via thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _run_command, cmd, timeout)


async def get_video_info(url: str) -> dict:
    """Get video metadata without downloading."""
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-download",
        "--no-playlist",
        "--no-check-certificates",
        url
    ]

    # For Douyin, add cookies workaround
    platform = detect_platform(url)
    if platform == "douyin":
        cmd.extend([
            "--extractor-args", "douyin:api_hostname=www.iesdouyin.com",
        ])

    returncode, stdout, stderr = await _run_command_async(cmd, timeout=60)

    if returncode == 0 and stdout.strip():
        try:
            info = json.loads(stdout)
            # Detect if this is a slideshow (no video formats, only audio + images)
            formats = info.get("formats", [])
            has_video_format = any(
                f.get("vcodec", "none") != "none"
                for f in formats
            )
            return {
                "title": info.get("title", ""),
                "description": info.get("description", ""),
                "duration": info.get("duration", 0),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "thumbnail": info.get("thumbnail", ""),
                "thumbnails": info.get("thumbnails", []),
                "uploader": info.get("uploader", ""),
                "view_count": info.get("view_count", 0),
                "like_count": info.get("like_count", 0),
                "platform": platform,
                "is_slideshow": not has_video_format,
                "raw_info": info,  # Keep full info for slideshow processing
            }
        except json.JSONDecodeError as e:
            return {"error": f"JSON parse error: {e}", "platform": platform}
    else:
        return {"error": stderr or "Unknown error", "platform": platform}


async def _download_tikwm(url: str, video_id: str) -> dict:
    """Download TikTok video using TikWM API (handles e-commerce product links)."""
    import httpx
    # Clean TikTok URL
    if "tiktok.com" in url:
        url = url.split("?")[0]
        
    logger.info(f"[{video_id}] Attempting to download via TikWM API (Clean URL: {url})...")
    output_dir = settings.DOWNLOAD_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.tikwm.com/"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            resp = await client.post("https://www.tikwm.com/api/", data={"url": url})
            data = resp.json()
            
            if data.get("code") != 0 or not data.get("data"):
                logger.warning(f"[{video_id}] TikWM API error: {data.get('msg', 'Unknown')}")
                return {"error": f"TikWM API error: {data.get('msg', 'Unknown')}"}
                
            video_data = data["data"]
            play_url = video_data.get("play")
            
            if not play_url:
                if video_data.get("images"):
                    # It's a slideshow, let yt-dlp handle it or handle it here
                    return {"error": "Slideshow detected in TikWM, falling back to yt-dlp."}
                return {"error": "No play URL found in TikWM response"}
            
            # Download the video MP4 file
            output_file = os.path.join(output_dir, f"{video_id}_tikwm.mp4")
            title = video_data.get("title", "")
            
            # Use streaming to download
            async with client.stream("GET", play_url) as stream_resp:
                if stream_resp.status_code != 200:
                    return {"error": f"Failed to download MP4, status {stream_resp.status_code}"}
                    
                total_size = int(stream_resp.headers.get("Content-Length", 0))
                downloaded = 0
                
                with open(output_file, "wb") as f:
                    async for chunk in stream_resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            video_progress[video_id] = round((downloaded / total_size) * 100, 1)
                            
            file_size = os.path.getsize(output_file)
            probe_info = await probe_video(output_file)
            
            # Try to get thumbnail
            thumbnail_url = video_data.get("cover", "")
            thumbnail_file = ""
            if thumbnail_url:
                try:
                    thumb_resp = await client.get(thumbnail_url)
                    if thumb_resp.status_code == 200:
                        thumbnail_file = os.path.join(output_dir, f"{video_id}_thumb.jpg")
                        with open(thumbnail_file, "wb") as f:
                            f.write(thumb_resp.content)
                except Exception:
                    pass
            
            result = {
                "id": video_id,
                "source_url": url,
                "source_platform": "tiktok",
                "title": title,
                "description": title,  # Content desc is often empty or list
                "original_path": output_file,
                "original_filename": os.path.basename(output_file),
                "thumbnail_path": thumbnail_file,
                "file_size": file_size,
                "duration": probe_info.get("duration", video_data.get("duration", 0)),
                "width": probe_info.get("width", 1080),
                "height": probe_info.get("height", 1920),
                "status": "downloaded",
            }
            
            await db.update_video(video_id, result)
            logger.info(f"[{video_id}] Download completed via TikWM: {output_file}")
            return result
            
    except Exception as e:
        logger.error(f"[{video_id}] TikWM Error: {e}")
        return {"error": str(e)}


async def _download_slideshow(url: str, video_id: str, info: dict) -> dict:
    """
    Handle TikTok slideshow posts (images + audio).
    Downloads all images and audio, then merges into MP4 using FFmpeg.
    """
    import httpx

    platform = info.get("platform", "tiktok")
    output_dir = settings.DOWNLOAD_DIR
    slideshow_dir = os.path.join(output_dir, f"{video_id}_slideshow")
    os.makedirs(slideshow_dir, exist_ok=True)

    title = info.get("title", "")
    description = info.get("description", "")
    raw_info = info.get("raw_info", {})

    logger.info(f"[{video_id}] Detected slideshow, downloading images + audio...")
    video_progress[video_id] = 10

    try:
        # 1. Extract image URLs from thumbnails/formats
        image_urls = []

        # TikTok slideshows store images in thumbnails with specific naming
        for thumb in raw_info.get("thumbnails", []):
            thumb_url = thumb.get("url", "")
            # TikTok slideshow images are typically in jpeg format under specific paths
            if thumb_url and ("image" in thumb.get("id", "") or
                             "slideshow" in thumb_url.lower() or
                             "musically" in thumb_url.lower() or
                             thumb.get("id", "").startswith("postpage_image")):
                image_urls.append(thumb_url)

        # Fallback: if no specific slideshow images, try to get images from the info
        if not image_urls:
            # Some TikTok slideshow videos store images in a different structure
            for thumb in raw_info.get("thumbnails", []):
                thumb_url = thumb.get("url", "")
                # Skip tiny thumbnails (width < 200 or contains "100x100")
                if thumb_url and "100x100" not in thumb_url and "avatar" not in thumb_url:
                    w = thumb.get("width", 0)
                    h = thumb.get("height", 0)
                    if w >= 200 or (w == 0 and h == 0):
                        image_urls.append(thumb_url)

        if not image_urls:
            # Last fallback: use the main thumbnail at least
            main_thumb = raw_info.get("thumbnail", "")
            if main_thumb:
                image_urls = [main_thumb]

        logger.info(f"[{video_id}] Found {len(image_urls)} slideshow images")
        video_progress[video_id] = 20

        # 2. Download all images
        image_files = []
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for i, img_url in enumerate(image_urls):
                try:
                    resp = await client.get(img_url)
                    if resp.status_code == 200:
                        ext = "jpg"
                        if "png" in resp.headers.get("content-type", ""):
                            ext = "png"
                        elif "webp" in resp.headers.get("content-type", ""):
                            ext = "webp"
                        img_path = os.path.join(slideshow_dir, f"img_{i:03d}.{ext}")
                        with open(img_path, "wb") as f:
                            f.write(resp.content)
                        image_files.append(img_path)
                except Exception as e:
                    logger.warning(f"[{video_id}] Failed to download image {i}: {e}")

        if not image_files:
            return {"error": "Không tải được ảnh nào từ slideshow", "id": video_id}

        video_progress[video_id] = 40

        # 3. Download audio using yt-dlp
        audio_path = os.path.join(slideshow_dir, "audio.mp3")
        audio_cmd = [
            "yt-dlp",
            "-f", "bestaudio",
            "--no-playlist",
            "--no-check-certificates",
            "-o", audio_path,
            url,
        ]

        loop = asyncio.get_event_loop()
        audio_rc, audio_output = await loop.run_in_executor(
            _executor, _run_yt_dlp_sync, audio_cmd, video_id, 120
        )

        has_audio = audio_rc == 0 and os.path.exists(audio_path)
        video_progress[video_id] = 60

        # 4. Get audio duration (or default 3s per image)
        duration_per_image = 3  # seconds per slide
        total_duration = duration_per_image * len(image_files)

        if has_audio:
            probe_result = await probe_video(audio_path)
            audio_duration = probe_result.get("duration", 0)
            if audio_duration > 0:
                duration_per_image = audio_duration / len(image_files)
                total_duration = audio_duration

        # 5. Create FFmpeg concat input file
        concat_file = os.path.join(slideshow_dir, "concat.txt")
        with open(concat_file, "w", encoding="utf-8") as f:
            for img in image_files:
                # Escape single quotes in path for FFmpeg
                safe_path = img.replace("\\", "/").replace("'", "'\\''")
                f.write(f"file '{safe_path}'\n")
                f.write(f"duration {duration_per_image}\n")
            # Repeat last image (FFmpeg concat demuxer requirement)
            safe_path = image_files[-1].replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

        video_progress[video_id] = 70

        # 6. Merge images + audio into MP4 with FFmpeg
        output_file = os.path.join(output_dir, f"{video_id}_slideshow.mp4")
        ffmpeg = get_ffmpeg_path()

        ffmpeg_cmd = [
            ffmpeg,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
        ]

        if has_audio:
            ffmpeg_cmd.extend(["-i", audio_path])

        ffmpeg_cmd.extend([
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "23",
            "-r", "30",
            "-pix_fmt", "yuv420p",
        ])

        if has_audio:
            ffmpeg_cmd.extend([
                "-c:a", "aac",
                "-b:a", "128k",
                "-shortest",
            ])

        ffmpeg_cmd.append(output_file)

        logger.info(f"[{video_id}] Creating slideshow video with FFmpeg...")
        merge_rc, merge_stdout, merge_stderr = await _run_command_async(ffmpeg_cmd, timeout=120)

        video_progress[video_id] = 90

        if merge_rc != 0 or not os.path.exists(output_file):
            error_msg = f"FFmpeg merge failed: {merge_stderr[-300:]}"
            logger.error(f"[{video_id}] {error_msg}")
            return {"error": error_msg, "id": video_id}

        # 7. Get final video info
        file_size = os.path.getsize(output_file)
        probe_info = await probe_video(output_file)

        # Use first image as thumbnail
        thumbnail_file = image_files[0] if image_files else ""

        video_progress[video_id] = 100

        result = {
            "id": video_id,
            "source_url": url,
            "source_platform": platform,
            "title": title or "TikTok Slideshow",
            "description": description,
            "original_path": output_file,
            "original_filename": os.path.basename(output_file),
            "thumbnail_path": thumbnail_file,
            "file_size": file_size,
            "duration": probe_info.get("duration", total_duration),
            "width": probe_info.get("width", 1080),
            "height": probe_info.get("height", 1920),
            "status": "downloaded",
        }

        await db.update_video(video_id, result)
        logger.info(f"[{video_id}] Slideshow video created: {output_file} ({len(image_files)} images, {total_duration:.1f}s)")
        return result

    except Exception as e:
        error_msg = f"Slideshow error: {type(e).__name__}: {str(e)}"
        logger.error(f"[{video_id}] {error_msg}")
        return {"error": error_msg, "id": video_id}


async def download_video(url: str, video_id: str = None,
                          progress_callback=None) -> dict:
    """
    Download video from URL using yt-dlp.
    Handles both regular videos and TikTok slideshows.
    Returns dict with file info or error.
    """
    if not video_id:
        video_id = str(uuid.uuid4())[:8]

    platform = detect_platform(url)
    output_dir = settings.DOWNLOAD_DIR
    os.makedirs(output_dir, exist_ok=True)

    # ----------------------------------------------------
    # FALLBACK FOR TIKTOK Affiliate Videos
    # ----------------------------------------------------
    # Ensure clean URL for TikTok
    if platform == "tiktok":
        clean_url = url.split("?")[0]
        tikwm_result = await _download_tikwm(clean_url, video_id)
        if tikwm_result and "error" not in tikwm_result:
            return tikwm_result
        else:
            logger.warning(f"[{video_id}] TikWM fallback failed for TikTok Shop, trying yt-dlp... Error: {tikwm_result.get('error', '')}")

    # Step 1: Get video info first (title, description, slideshow detection)
    title = ""
    description = ""
    info = {}
    try:
        info = await get_video_info(url)
        if "error" not in info:
            title = info.get("title", "")
            description = info.get("description", "")
    except Exception:
        pass

    # Step 2: Check if this is a slideshow (no video formats)
    if info.get("is_slideshow"):
        logger.info(f"[{video_id}] Slideshow detected! Switching to image+audio mode...")
        await db.update_video(video_id, {
            "status": "downloading",
            "title": title or "TikTok Slideshow",
            "description": description,
        })
        result = await _download_slideshow(url, video_id, info)
        if "error" in result:
            await db.update_video(video_id, {
                "status": "failed",
                "error_message": result["error"][:500],
            })
        return result

    # Step 3: Normal video download
    # Output template - use ONLY video_id + platform_id to avoid Unicode issues
    output_template = os.path.join(output_dir, f"{video_id}_%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "bestvideo*+bestaudio/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--no-check-certificates",
        "--restrict-filenames",
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "-o", output_template,
        "--encoding", "utf-8",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]

    # Platform-specific options
    if platform == "douyin":
        cmd.extend([
            "--extractor-args", "douyin:api_hostname=www.iesdouyin.com",
        ])
    elif platform == "facebook":
        cmd.extend([
            "--cookies-from-browser", "chrome",
        ])

    cmd.append(url)

    logger.info(f"Starting download: {url} -> {video_id}")

    try:
        # Update status in DB
        await db.update_video(video_id, {
            "status": "downloading",
            "title": title,
            "description": description,
        })

        # Run yt-dlp with progress parsing in thread pool
        loop = asyncio.get_event_loop()
        returncode, all_output = await loop.run_in_executor(
            _executor, _run_yt_dlp_sync, cmd, video_id, 300
        )

        logger.info(f"yt-dlp [{video_id}] exit code: {returncode}")

        if returncode == 0:
            # Find the downloaded file
            downloaded_file = None
            thumbnail_file = None

            for f in os.listdir(output_dir):
                if f.startswith(video_id):
                    full_path = os.path.join(output_dir, f)
                    if f.endswith(('.mp4', '.mkv', '.webm', '.avi')):
                        downloaded_file = full_path
                    elif f.endswith(('.jpg', '.png', '.webp')):
                        thumbnail_file = full_path

            if downloaded_file:
                # Get file info
                file_size = os.path.getsize(downloaded_file)

                # Get video info with ffprobe
                probe_info = await probe_video(downloaded_file)

                result = {
                    "id": video_id,
                    "source_url": url,
                    "source_platform": platform,
                    "title": title,
                    "description": description,
                    "original_path": downloaded_file,
                    "original_filename": os.path.basename(downloaded_file),
                    "thumbnail_path": thumbnail_file or "",
                    "file_size": file_size,
                    "duration": probe_info.get("duration", 0),
                    "width": probe_info.get("width", 0),
                    "height": probe_info.get("height", 0),
                    "status": "downloaded",
                }

                # Update database
                await db.update_video(video_id, result)
                logger.info(f"Download completed: {video_id} -> {downloaded_file}")
                return result
            else:
                # Log the output for debugging
                last_output = all_output[-1000:] if all_output else "No output"
                error_msg = f"Download completed but file not found (prefix: {video_id}). Log: {last_output}"
                logger.error(f"[{video_id}] {error_msg}")
                
                # Check directory contents for debug
                try:
                    files_in_dir = os.listdir(output_dir)
                    logger.info(f"[{video_id}] Files in {output_dir}: {files_in_dir[:20]}")
                except Exception:
                    pass

                await db.update_video(video_id, {
                    "status": "failed",
                    "error_message": f"File not found. Check logs for details."
                })
                return {"error": error_msg, "id": video_id}
        else:
            # Extract error from output
            error_lines = [l for l in all_output.split('\n') if 'ERROR' in l]
            error = '\n'.join(error_lines) if error_lines else all_output[-500:]
            logger.error(f"[{video_id}] Download failed: {error}")
            await db.update_video(video_id, {
                "status": "failed",
                "error_message": error[:500]
            })
            return {"error": error, "id": video_id}

    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        logger.error(f"[{video_id}] Exception: {error_msg}")
        await db.update_video(video_id, {
            "status": "failed",
            "error_message": error_msg
        })
        return {"error": error_msg, "id": video_id}


async def probe_video(file_path: str) -> dict:
    """Get video metadata using ffprobe."""
    ffprobe = settings.FFMPEG_PATH.replace("ffmpeg", "ffprobe") if settings.FFMPEG_PATH else "ffprobe"

    cmd = [
        ffprobe,
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        file_path
    ]

    returncode, stdout, stderr = await _run_command_async(cmd, timeout=30)

    if returncode == 0 and stdout.strip():
        try:
            info = json.loads(stdout)
            video_stream = None
            for stream in info.get("streams", []):
                if stream.get("codec_type") == "video":
                    video_stream = stream
                    break

            fps = 0
            if video_stream and video_stream.get("r_frame_rate"):
                try:
                    parts = video_stream["r_frame_rate"].split("/")
                    if len(parts) == 2 and int(parts[1]) != 0:
                        fps = int(parts[0]) / int(parts[1])
                except (ValueError, ZeroDivisionError):
                    pass

            return {
                "duration": float(info.get("format", {}).get("duration", 0)),
                "width": int(video_stream.get("width", 0)) if video_stream else 0,
                "height": int(video_stream.get("height", 0)) if video_stream else 0,
                "codec": video_stream.get("codec_name", "") if video_stream else "",
                "fps": fps,
                "bitrate": int(info.get("format", {}).get("bit_rate", 0)),
            }
        except Exception:
            pass

    return {"duration": 0, "width": 0, "height": 0}


async def batch_download(urls: list[str], progress_callback=None) -> list[dict]:
    """Download multiple videos."""
    results = []
    for i, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue

        video_id = str(uuid.uuid4())[:8]

        # Create initial DB record
        await db.create_video({
            "id": video_id,
            "source_url": url,
            "source_platform": detect_platform(url),
            "status": "pending",
        })

        result = await download_video(url, video_id, progress_callback)
        results.append(result)

    return results
