"""
ReupMaster Pro - Video Processor Service
FFmpeg-based video processing for copyright avoidance.
Applies multiple transformations to make videos unique.

Uses subprocess.run in thread pool to avoid asyncio subprocess issues on Windows.
"""
import os
import re
import uuid
import json
import asyncio
import subprocess
import logging
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app import database as db
from app.services.progress import video_progress

logger = logging.getLogger("reupmaster.processor")

# Thread pool for running FFmpeg commands
_executor = ThreadPoolExecutor(max_workers=2)


def get_ffmpeg() -> str:
    """Get FFmpeg executable path."""
    return settings.FFMPEG_PATH if settings.FFMPEG_PATH else "ffmpeg"


def _run_ffmpeg(cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
    """Run FFmpeg command synchronously (called from thread pool)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            text=False,
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        return result.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        return -1, "", "FFmpeg command timed out"
    except Exception as e:
        return -1, "", str(e)


async def _run_ffmpeg_async(cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
    """Run FFmpeg command asynchronously via thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _run_ffmpeg, cmd, timeout)


def _run_ffmpeg_sync_with_progress(cmd: list[str], video_id: str, duration: float, timeout: int = 600) -> tuple[int, str]:
    """Run FFmpeg, parse progress from stderr, update global video_progress dict."""
    try:
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

            if "time=" in line_str and duration > 0:
                time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line_str)
                if time_match:
                    h, m, s = time_match.groups()
                    current_time = int(h) * 3600 + int(m) * 60 + float(s)
                    pct = min(99, (current_time / duration) * 100)
                    video_progress[video_id] = pct

        process.wait(timeout=timeout)
        return process.returncode, "".join(all_output)
    except subprocess.TimeoutExpired:
        if process:
            process.kill()
        return -1, "".join(all_output) + "\ntimeout"
    except Exception as e:
        return -1, str(e)


class VideoProcessor:
    """
    Video processing engine using FFmpeg.
    Applies transformations to make re-uploaded videos unique.
    """

    # Available processing options with descriptions
    AVAILABLE_OPTIONS = {
        "mirror": {
            "name": "Lật gương (Mirror)",
            "description": "Lật ngang video để thay đổi khung hình",
            "default": True
        },
        "speed": {
            "name": "Thay đổi tốc độ",
            "description": "Tăng/giảm tốc độ nhẹ (0.95-1.05)",
            "default": True,
            "value": 1.03
        },
        "brightness": {
            "name": "Điều chỉnh sáng",
            "description": "Thay đổi độ sáng nhẹ",
            "default": True,
            "value": 0.05
        },
        "contrast": {
            "name": "Điều chỉnh tương phản",
            "description": "Thay đổi contrast nhẹ",
            "default": True,
            "value": 1.05
        },
        "saturation": {
            "name": "Điều chỉnh bão hòa",
            "description": "Thay đổi saturation nhẹ",
            "default": True,
            "value": 1.1
        },
        "crop": {
            "name": "Crop nhẹ",
            "description": "Cắt 1-2% mỗi cạnh để thay đổi frame",
            "default": True,
            "value": 0.02
        },
        "noise": {
            "name": "Thêm noise",
            "description": "Thêm nhiễu nhẹ không thấy được",
            "default": True,
            "value": 3
        },
        "border": {
            "name": "Thêm viền",
            "description": "Thêm viền mỏng xung quanh video",
            "default": False,
            "value": 2,
            "color": "black"
        },
        "rotate": {
            "name": "Xoay nhẹ",
            "description": "Xoay video 0.5-1 độ",
            "default": False,
            "value": 0.5
        },
        "blur_edges": {
            "name": "Làm mờ viền",
            "description": "Blur nhẹ vùng viền video",
            "default": False,
            "value": 3
        },
        "change_fps": {
            "name": "Đổi FPS",
            "description": "Thay đổi frame rate",
            "default": True,
            "value": 29
        },
        "change_resolution": {
            "name": "Đổi độ phân giải",
            "description": "Scale lại video (vd: 1078x1920)",
            "default": False,
            "value": "1078x1920"
        },
        "add_watermark_text": {
            "name": "Thêm watermark text",
            "description": "Thêm text watermark nhỏ, trong suốt",
            "default": False,
            "value": "",
            "opacity": 0.15,
            "position": "bottom_right"
        },
        "reencode": {
            "name": "Re-encode",
            "description": "Encode lại với codec khác (thay đổi binary)",
            "default": True,
            "codec": "libx264",
            "crf": 18
        },
        "change_metadata": {
            "name": "Xóa/Đổi metadata",
            "description": "Xóa toàn bộ metadata gốc",
            "default": True
        },
        "add_silence": {
            "name": "Thêm khoảng lặng",
            "description": "Thêm 0.1-0.5s silence đầu/cuối",
            "default": True,
            "value": 0.2
        },
        "pitch_shift": {
            "name": "Đổi pitch âm thanh",
            "description": "Thay đổi nhẹ pitch âm thanh",
            "default": True,
            "value": 1.02
        },
        "remove_audio": {
            "name": "Xóa âm thanh gốc",
            "description": "Loại bỏ audio gốc (dùng khi muốn thay bằng AI voice)",
            "default": False
        },
        # ─── Deep Anti-Copyright (Advanced) ───
        "ghost_overlay": {
            "name": "👻 Ghost Overlay (1-2% layer ẩn)",
            "description": "Chèn layer mờ 1-2% không nhìn thấy, thay đổi mã hash hoàn toàn",
            "default": False,
            "value": 0.015
        },
        "deep_noise": {
            "name": "🔬 Deep Noise (Hash Breaker)",
            "description": "Thêm noise cực nhỏ không nhìn thấy (mắt không phân biệt được)",
            "default": False,
            "value": 1
        },
        "pixel_shift": {
            "name": "🔄 Pixel Shift (Sub-pixel)",
            "description": "Dịch chuyển pixel ở mức sub-pixel, phá vỡ fingerprint",
            "default": False,
            "value": 1
        },
        "color_channel_shift": {
            "name": "🎨 Color Channel Shift",
            "description": "Dịch kênh màu RGB nhẹ (không ảnh hưởng visual nhưng đổi hash)",
            "default": False,
            "value": 2
        },
        "random_metadata": {
            "name": "🎲 Random Metadata",
            "description": "Ghi đè metadata giả ngẫu nhiên (device, date, GPS...)",
            "default": True
        },
    }

    @staticmethod
    def build_filter_complex(options: dict, width: int = 0, height: int = 0) -> str:
        """Build FFmpeg filter_complex string from options."""
        video_filters = []
        audio_filters = []

        # Mirror / Horizontal Flip
        if options.get("mirror", False):
            video_filters.append("hflip")

        # Crop slightly
        if options.get("crop", False):
            crop_pct = float(options.get("crop_value", 0.02))
            if width and height:
                cw = int(width * (1 - crop_pct))
                ch = int(height * (1 - crop_pct))
                video_filters.append(f"crop={cw}:{ch}")

        # Brightness, Contrast, Saturation
        eq_parts = []
        if options.get("brightness", False):
            bri = float(options.get("brightness_value", 0.05))
            eq_parts.append(f"brightness={bri}")
        if options.get("contrast", False):
            con = float(options.get("contrast_value", 1.05))
            eq_parts.append(f"contrast={con}")
        if options.get("saturation", False):
            sat = float(options.get("saturation_value", 1.1))
            eq_parts.append(f"saturation={sat}")
        if eq_parts:
            video_filters.append(f"eq={':'.join(eq_parts)}")

        # Noise
        if options.get("noise", False):
            noise_val = int(options.get("noise_value", 3))
            video_filters.append(f"noise=alls={noise_val}:allf=t+u")

        # Rotate slightly
        if options.get("rotate", False):
            rot_deg = float(options.get("rotate_value", 0.5))
            rot_rad = rot_deg * 3.14159 / 180
            video_filters.append(f"rotate={rot_rad}:c=black:ow=rotw({rot_rad}):oh=roth({rot_rad})")

        # Change resolution  
        if options.get("change_resolution", False):
            res = options.get("resolution_value", "1078x1920")
            if "x" in str(res):
                w, h = res.split("x")
                video_filters.append(f"scale={w}:{h}")

        # Add border
        if options.get("border", False):
            border_size = int(options.get("border_value", 2))
            color = options.get("border_color", "black")
            video_filters.append(f"pad=iw+{border_size*2}:ih+{border_size*2}:{border_size}:{border_size}:{color}")

        # Add watermark text
        if options.get("add_watermark_text", False):
            text = options.get("add_watermark_text_value", options.get("watermark_text", ""))
            if text:
                opacity = float(options.get("add_watermark_text_opacity", options.get("watermark_opacity", 0.35)))
                pos = options.get("add_watermark_text_position", options.get("watermark_position", "bottom_right"))
                font_size = 24

                # Position mapping
                pos_map = {
                    "top_left": "x=10:y=10",
                    "top_right": "x=w-tw-10:y=10",
                    "bottom_left": "x=10:y=h-th-10",
                    "bottom_right": "x=w-tw-10:y=h-th-10",
                    "center": "x=(w-tw)/2:y=(h-th)/2",
                }
                pos_str = pos_map.get(pos, pos_map["bottom_right"])

                # Escape special characters for FFmpeg
                text_escaped = text.replace("'", "\\'").replace(":", "\\:")
                video_filters.append(
                    f"drawtext=text='{text_escaped}':fontsize={font_size}:"
                    f"{pos_str}:fontcolor=white@{opacity}"
                )

        # Speed change (affects both video and audio)
        if options.get("speed", False):
            spd = float(options.get("speed_value", 1.03))
            video_filters.append(f"setpts={1/spd}*PTS")
            if not options.get("remove_audio", False):
                audio_filters.append(f"atempo={spd}")

        # Pitch shift audio
        if options.get("pitch_shift", False) and not options.get("remove_audio", False):
            pitch = float(options.get("pitch_value", 1.02))
            audio_filters.append(f"asetrate=44100*{pitch},aresample=44100")

        # ─── Deep Anti-Copyright Filters ───

        # Ghost Overlay: blend a colored layer at very low opacity
        # This changes every single frame's pixel data without visible effect
        if options.get("ghost_overlay", False):
            opacity = float(options.get("ghost_overlay_value", 0.015))
            # Create a semi-transparent colored noise overlay
            # geq filter: add tiny random-like variation to each channel
            video_filters.append(
                f"geq=r='clip(r(X,Y)+{int(opacity*255)}, 0, 255)':"
                f"g='clip(g(X,Y)-{int(opacity*128)}, 0, 255)':"
                f"b='clip(b(X,Y)+{int(opacity*64)}, 0, 255)'"
            )

        # Deep Noise: extremely subtle noise that's imperceptible
        # but completely changes the binary hash of every frame
        if options.get("deep_noise", False):
            noise_level = int(options.get("deep_noise_value", 1))
            # Use temporal + uniform noise at very low level
            video_filters.append(f"noise=c0s={noise_level}:c0f=t+u:c1s={noise_level}:c1f=t+u:c2s={noise_level}:c2f=t+u")

        # Pixel Shift: apply sub-pixel displacement
        # Moves image by fractional pixels - machine detectable change, human invisible
        if options.get("pixel_shift", False):
            shift = int(options.get("pixel_shift_value", 1))
            # Pad then crop to shift content by N pixels
            video_filters.append(f"pad=iw+{shift}:ih+{shift}:{shift}:{shift}:black")
            video_filters.append(f"crop=iw-{shift}:ih-{shift}:0:0")

        # Color Channel Shift: slightly offset RGB channels
        if options.get("color_channel_shift", False):
            shift_val = int(options.get("color_channel_shift_value", 2))
            video_filters.append(
                f"geq=r='r(X,Y)':g='g(X+{shift_val},Y)':b='b(X,Y+{shift_val})'"
            )

        return video_filters, audio_filters

    @staticmethod
    async def process_video(video_id: str, options: dict,
                            progress_callback=None) -> dict:
        """
        Process a video with given options.
        Returns dict with processed file info.
        """
        # Get video from DB
        video = await db.get_video(video_id)
        if not video:
            return {"error": f"Video {video_id} not found"}

        input_path = video["original_path"]
        if not os.path.exists(input_path):
            return {"error": f"Source file not found: {input_path}"}

        # Generate output filename
        output_filename = f"processed_{video_id}_{uuid.uuid4().hex[:6]}.mp4"
        output_path = os.path.join(settings.PROCESSED_DIR, output_filename)
        os.makedirs(settings.PROCESSED_DIR, exist_ok=True)

        # Update status
        await db.update_video(video_id, {
            "status": "processing",
            "processing_options": json.dumps(options)
        })

        logger.info(f"Processing video {video_id}: {input_path}")

        try:
            # Build FFmpeg command
            width = video.get("width", 0) or 0
            height = video.get("height", 0) or 0
            video_filters, audio_filters = VideoProcessor.build_filter_complex(
                options, width, height
            )

            # Build command
            cmd = [get_ffmpeg(), "-y", "-i", input_path]

            # Add silence at beginning if requested
            add_silence = options.get("add_silence", False)
            silence_duration = float(options.get("silence_value", 0.2))

            # Build filter strings
            vf_str = ",".join(video_filters) if video_filters else None
            af_str = ",".join(audio_filters) if audio_filters else None

            if vf_str:
                cmd.extend(["-vf", vf_str])

            if options.get("remove_audio", False):
                cmd.extend(["-an"])  # No audio
            elif af_str:
                cmd.extend(["-af", af_str])

            # Codec settings
            if options.get("reencode", True):
                codec = options.get("codec", "libx264")
                crf = int(options.get("crf", 18))
                cmd.extend([
                    "-c:v", codec,
                    "-crf", str(crf),
                    "-preset", "medium",
                    "-pix_fmt", "yuv420p",
                ])
                if not options.get("remove_audio", False):
                    cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            else:
                cmd.extend(["-c", "copy"])

            # Change FPS
            if options.get("change_fps", False):
                fps = int(options.get("fps_value", 29))
                cmd.extend(["-r", str(fps)])

            # Remove metadata
            if options.get("change_metadata", True):
                cmd.extend(["-map_metadata", "-1"])

            # Random Metadata: write fake metadata to further disguise origin
            if options.get("random_metadata", True):
                import random
                fake_devices = ["iPhone 15 Pro", "Samsung Galaxy S24", "Xiaomi 14", "OPPO Find X7", "Google Pixel 9", "Huawei P60"]
                fake_sw = ["CapCut 12.0", "InShot 2.0", "Adobe Premiere 2026", "DaVinci Resolve 20", "VN Video Editor 3.0"]
                fake_date = f"202{random.randint(3,6)}-{random.randint(1,12):02d}-{random.randint(1,28):02d}T{random.randint(6,22):02d}:{random.randint(0,59):02d}:{random.randint(0,59):02d}"
                cmd.extend([
                    "-metadata", f"creation_time={fake_date}",
                    "-metadata", f"encoder={random.choice(fake_sw)}",
                    "-metadata", f"comment=Edited on {random.choice(fake_devices)}",
                    "-metadata", f"artist=User{random.randint(1000,9999)}",
                ])

            # Output
            cmd.append(output_path)

            logger.info(f"FFmpeg cmd: {' '.join(cmd)}")

            # Execute FFmpeg in thread pool with progress tracking
            duration = video.get("duration", 0) or 0
            loop = asyncio.get_event_loop()
            returncode, all_output = await loop.run_in_executor(
                _executor, _run_ffmpeg_sync_with_progress, cmd, video_id, float(duration), 600
            )

            logger.info(f"FFmpeg [{video_id}] exit code: {returncode}")

            if returncode == 0 and os.path.exists(output_path):
                file_size = os.path.getsize(output_path)

                # Handle silence padding if needed
                if add_silence and silence_duration > 0:
                    output_path = await VideoProcessor._add_silence_padding(
                        output_path, silence_duration
                    )
                    file_size = os.path.getsize(output_path)

                result = {
                    "processed_path": output_path,
                    "status": "processed",
                    "file_size": file_size,
                }
                
                # Make sure progress hits 100 on complete
                video_progress[video_id] = 100.0
                
                await db.update_video(video_id, result)

                logger.info(f"Processing completed: {video_id} -> {output_path} ({file_size} bytes)")

                if progress_callback:
                    await progress_callback(video_id, 100)

                return {**result, "id": video_id}
            else:
                error = all_output[-500:] if all_output else "Unknown FFmpeg error"
                logger.error(f"FFmpeg [{video_id}] failed: {error}")
                await db.update_video(video_id, {
                    "status": "failed",
                    "error_message": f"FFmpeg error: {error}"
                })
                return {"error": error, "id": video_id}

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"Processing [{video_id}] exception: {error_msg}")
            await db.update_video(video_id, {
                "status": "failed",
                "error_message": error_msg
            })
            return {"error": error_msg, "id": video_id}

    @staticmethod
    async def _add_silence_padding(video_path: str, duration: float) -> str:
        """Add silence padding to beginning and end of video."""
        temp_path = video_path.replace(".mp4", "_padded.mp4")

        cmd = [
            get_ffmpeg(), "-y",
            "-f", "lavfi", "-t", str(duration),
            "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
            "-i", video_path,
            "-f", "lavfi", "-t", str(duration),
            "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
            "-filter_complex",
            "[2:a][1:a][0:a]concat=n=3:v=0:a=1[aout]",
            "-map", "1:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest",
            temp_path
        ]

        returncode, stdout, stderr = await _run_ffmpeg_async(cmd, timeout=120)

        if returncode == 0 and os.path.exists(temp_path):
            os.replace(temp_path, video_path)

        return video_path

    @staticmethod
    async def batch_process(video_ids: list[str], options: dict,
                            progress_callback=None) -> list[dict]:
        """Process multiple videos with same options."""
        results = []
        for vid_id in video_ids:
            result = await VideoProcessor.process_video(
                vid_id, options, progress_callback
            )
            results.append(result)
        return results

    @staticmethod
    def get_default_options() -> dict:
        """Get default processing options."""
        defaults = {}
        for key, opt in VideoProcessor.AVAILABLE_OPTIONS.items():
            defaults[key] = opt.get("default", False)
            if "value" in opt:
                defaults[f"{key}_value"] = opt["value"]
        return defaults
