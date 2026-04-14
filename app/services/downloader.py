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
            return {
                "title": info.get("title", ""),
                "description": info.get("description", ""),
                "duration": info.get("duration", 0),
                "width": info.get("width", 0),
                "height": info.get("height", 0),
                "thumbnail": info.get("thumbnail", ""),
                "uploader": info.get("uploader", ""),
                "view_count": info.get("view_count", 0),
                "like_count": info.get("like_count", 0),
                "platform": platform,
            }
        except json.JSONDecodeError as e:
            return {"error": f"JSON parse error: {e}", "platform": platform}
    else:
        return {"error": stderr or "Unknown error", "platform": platform}


async def download_video(url: str, video_id: str = None,
                          progress_callback=None) -> dict:
    """
    Download video from URL using yt-dlp.
    Returns dict with file info or error.
    """
    if not video_id:
        video_id = str(uuid.uuid4())[:8]

    platform = detect_platform(url)
    output_dir = settings.DOWNLOAD_DIR
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Get video info first (title, description, etc.)
    title = ""
    description = ""
    try:
        info = await get_video_info(url)
        if "error" not in info:
            title = info.get("title", "")
            description = info.get("description", "")
    except Exception:
        pass

    # Output template - use ONLY video_id + platform_id to avoid Unicode issues
    output_template = os.path.join(output_dir, f"{video_id}_%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "-f", "best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "--no-check-certificates",
        "--restrict-filenames",
        "--write-thumbnail",
        "--convert-thumbnails", "jpg",
        "-o", output_template,
        "--encoding", "utf-8",
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
                error_msg = f"Download completed but file not found (prefix: {video_id})"
                logger.error(f"[{video_id}] {error_msg}")
                await db.update_video(video_id, {
                    "status": "failed",
                    "error_message": error_msg
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
