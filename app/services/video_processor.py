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
from app.services.progress import video_progress, video_logs, active_processes

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
        # FFmpeg writes progress to stderr. We pipe stderr to parse it.
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace'
        )
        
        active_processes[video_id] = process

        all_output = []
        if video_id not in video_logs:
            video_logs[video_id] = []
            
        # Read stderr line by line (FFmpeg outputs progress here)
        for line in process.stderr:
            all_output.append(line)
            line_str = line.strip()
            
            video_logs[video_id].append(line_str)
            if len(video_logs[video_id]) > 100:
                video_logs[video_id].pop(0)

            if "time=" in line_str and duration > 0:
                time_match = re.search(r'time=(\d+):(\d+):(\d+\.?\d*)', line_str)
                if time_match:
                    h, m, s = time_match.groups()
                    current_time = int(h) * 3600 + int(m) * 60 + float(s)
                    pct = min(99, (current_time / duration) * 100)
                    video_progress[video_id] = round(pct, 1)

        process.wait(timeout=timeout)
        if video_id in active_processes:
            del active_processes[video_id]
        return process.returncode, "".join(all_output)
    except subprocess.TimeoutExpired:
        if video_id in active_processes:
            del active_processes[video_id]
        if process:
            process.kill()
        return -1, "".join(all_output) + "\ntimeout"
    except Exception as e:
        if video_id in active_processes:
            del active_processes[video_id]
        return -1, str(e)


class VideoProcessor:
    """
    Video processing engine using FFmpeg.
    Applies transformations to make re-uploaded videos unique.
    """
    
    @staticmethod
    async def process_images(original_dir: str, processed_dir: str, options: dict) -> bool:
        """Process a directory of images (flip, watermark)."""
        from PIL import Image, ImageDraw, ImageFont, ImageOps
        import shutil
        
        try:
            if not os.path.exists(processed_dir):
                os.makedirs(processed_dir, exist_ok=True)
                
            valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
            
            for f in os.listdir(original_dir):
                if os.path.splitext(f)[1].lower() not in valid_exts:
                    continue
                    
                input_path = os.path.join(original_dir, f)
                output_path = os.path.join(processed_dir, f)
                
                try:
                    with Image.open(input_path) as img:
                        # Convert to RGB if it's RGBA and we're saving as JPEG
                        if img.mode in ('RGBA', 'P') and f.lower().endswith(('.jpg', '.jpeg')):
                            img = img.convert('RGB')
                            
                        # Apply flip
                        if options.get("flip"):
                            img = ImageOps.mirror(img)
                            
                        # Apply watermark text
                        if options.get("watermark") and options.get("watermark_text"):
                            draw = ImageDraw.Draw(img)
                            text = options.get("watermark_text", "")
                            
                            # Try to load a font, fallback to default
                            try:
                                # font size relative to image height
                                font_size = max(14, int(img.height * 0.03))
                                font = ImageFont.truetype("arial.ttf", font_size)
                            except IOError:
                                font = ImageFont.load_default()
                                
                            # Text bounds
                            bbox = draw.textbbox((0, 0), text, font=font)
                            text_w = bbox[2] - bbox[0]
                            text_h = bbox[3] - bbox[1]
                            
                            # Position: random or center
                            import random
                            x = random.randint(10, max(11, img.width - text_w - 10))
                            y = random.randint(10, max(11, img.height - text_h - 10))
                            
                            # Draw shadow
                            draw.text((x+2, y+2), text, font=font, fill=(0, 0, 0, 128))
                            # Draw text
                            draw.text((x, y), text, font=font, fill=(255, 255, 255, 200))
                            
                        img.save(output_path, quality=90)
                except Exception as e:
                    logger.warning(f"Failed to process image {f}: {e}")
                    shutil.copy2(input_path, output_path)
                    
            return True
        except Exception as e:
            logger.error(f"Image processing failed: {e}")
            return False

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

        # ─── New Advanced Anti-Copyright (1-8) ───
        "temporal_blend": {
            "name": "🌪️ Temporal Blending",
            "description": "Trộn pixel giữa các frame, tạo motion blur nhẹ phá hash",
            "default": False,
            "mode": "average"
        },
        "frame_interpolation": {
            "name": "🎞️ Frame Interpolation",
            "description": "Nội suy frame mới 100% (rất nặng CPU)",
            "default": False,
            "fps": 60
        },
        "audio_breaker": {
            "name": "🔊 Phá Audio Fingerprint",
            "description": "Combo EQ + Reverb + Resample phá dấu vân tay âm thanh",
            "default": False
        },
        "dct_manipulation": {
            "name": "🧬 Cấu trúc nén DCT",
            "description": "Can thiệp tầng nén sâu (GOP, B-frames, Quantization)",
            "default": False
        },
        "image_watermark": {
            "name": "🖼️ Chèn Logo PNG (Watermark)",
            "description": "Chèn logo của bạn (nếu có) vào video để xây kênh",
            "default": False
        },
        "auto_intro_outro": {
            "name": "🧬 Cấu trúc nén DCT",
            "description": "Can thiệp tầng nén sâu (GOP, B-frames, Quantization)",
            "default": False
        },
        "dynamic_watermark": {
            "name": "🌊 Watermark di chuyển",
            "description": "Watermark chạy ngẫu nhiên khắp màn hình",
            "default": False,
            "text": "@ReupMaster"
        },
        "auto_intro_outro": {
            "name": "🎬 Auto Intro/Outro",
            "description": "Tự động thêm 1s video/ảnh mờ ở đầu và cuối",
            "default": False
        },
        "scene_reshuffle": {
            "name": "✂️ Đảo cảnh ngẫu nhiên",
            "description": "(BETA) Cắt video thành nhiều đoạn và đảo nhẹ thứ tự",
            "default": False
        },
        "ai_frame_variation": {
            "name": "🤖 AI Style Variation",
            "description": "(Mô phỏng AI) Thêm hiệu ứng nghệ thuật nhẹ để thay đổi hoàn toàn frame",
            "default": False
        },

        # ─── Vietsub & Lồng Tiếng ───
        "vietsub_dubbing": {
            "name": "🎙️ Vietsub + Lồng Tiếng",
            "description": "Tự động nhận diện giọng nói → Dịch → Phụ đề + Lồng tiếng Việt (AI)",
            "default": False,
            "voice_id": "vi-female",
            "voice_rate": "+0%",
            "sub_style": "default",
            "original_volume": 0.0,
        },
        "vietsub_only": {
            "name": "📝 Vietsub (Chỉ Phụ Đề)",
            "description": "Chỉ thêm phụ đề Việt, giữ nguyên âm thanh gốc (không lồng tiếng)",
            "default": False,
            "sub_style": "default",
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

        # Ghost Overlay: Use colorbalance for fast per-frame color shift
        # Changes entire frame hash without expensive per-pixel geq computation
        if options.get("ghost_overlay", False):
            opacity = float(options.get("ghost_overlay_value", 0.015))
            # colorbalance is GPU-friendly and modifies every pixel's RGB values
            rs = round(opacity * 2, 3)
            gm = round(-opacity, 3)
            bh = round(opacity * 0.5, 3)
            video_filters.append(f"colorbalance=rs={rs}:gm={gm}:bh={bh}")

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

        # Color Channel Shift: use hue rotate for fast channel manipulation
        # Much faster than geq while still modifying color data per-frame
        if options.get("color_channel_shift", False):
            shift_val = int(options.get("color_channel_shift_value", 2))
            # Use hue shift (very fast) + slight saturation tweak
            video_filters.append(f"hue=h={shift_val}:s=1")

        
        # ─── Advanced Anti-Copyright Filters (1-8) ───
        
        # 1. Temporal Blending
        if options.get("temporal_blend", False):
            # Fallback to 'average' if 'average128' was selected from the old options default
            mode = options.get("temporal_blend_mode", "average").replace("128", "")
            if mode == "average": mode = "average"
            video_filters.append(f"tblend=all_mode={mode}")
            
        # 2. Dynamic Watermark
        if options.get("dynamic_watermark", False):
            text = options.get("dynamic_watermark_text", "@ReupMaster")
            text_escaped = text.replace("'", "\'").replace(":", "\\:")
            # Use sin/cos for smooth movement or random jumps
            video_filters.append(
                f"drawtext=text='{text_escaped}':fontsize=24:fontcolor=white@0.15:"
                f"x='if(eq(mod(n\,300)\,0)\,random(1)*(W-tw)\,x)':"
                f"y='if(eq(mod(n\,300)\,0)\,random(1)*(H-th)\,y)'"
            )
            
        # 3. Audio Fingerprint Breaker
        if options.get("audio_breaker", False) and not options.get("remove_audio", False):
            audio_filters.append("aresample=48000")
            audio_filters.append("equalizer=f=100:t=q:w=1:g=2")
            audio_filters.append("equalizer=f=8000:t=q:w=1:g=-1")
            audio_filters.append("aecho=0.8:0.9:40:0.3")
            audio_filters.append("extrastereo=m=1.2")
            
        # 6. Auto Intro/Outro (Add 1s black padding)
        if options.get("auto_intro_outro", False):
            video_filters.append("tpad=start_duration=1:stop_duration=1:color=black")
            if not options.get("remove_audio", False):
                audio_filters.append("adelay=1s:all=1")
                audio_filters.append("apad=pad_dur=1")
                
        # 7. Scene Reshuffle (Randomize frame order slightly)
        if options.get("scene_reshuffle", False):
            video_filters.append("random=frames=3")
            
        # 8. AI Style Variation (Simulated with complex light filters)
        if options.get("ai_frame_variation", False):
            # Use unsharp mask and selective blur to create an "AI upscaled" painterly look
            video_filters.append("unsharp=5:5:1.0:5:5:0.0")
            video_filters.append("smartblur=1.5:-0.35:-3.5:0.5:0.25:2.0")
            
        # 3. Frame Interpolation (add last because it changes frame rate)
        if options.get("frame_interpolation", False):
            target_fps = int(options.get("frame_interpolation_fps", 60))
            video_filters.append(f"minterpolate=fps={target_fps}:mi_mode=blend")

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
            # ─── Vietsub + Lồng Tiếng Pipeline ───
            # This runs BEFORE normal processing so the output becomes the new input
            if options.get("vietsub_dubbing", False):
                logger.info(f"Vietsub pipeline triggered for {video_id}")
                from app.services.vietsub_service import full_vietsub_pipeline
                
                video_logs[video_id] = []
                video_progress[video_id] = 0.0

                def _vs_progress(step, msg):
                    video_logs[video_id].append(msg)
                    # Fake progress logic based on steps
                    if step == "extract": video_progress[video_id] = 10.0
                    elif step == "transcribe": video_progress[video_id] = 30.0
                    elif step == "translate": video_progress[video_id] = 50.0
                    elif step == "subtitle": video_progress[video_id] = 60.0
                    elif step == "voiceover": video_progress[video_id] = 80.0
                    elif step == "render": video_progress[video_id] = 95.0

                vietsub_result = await full_vietsub_pipeline(
                    video_path=input_path,
                    voice_id=options.get("vietsub_dubbing_voice_id", "vi-female"),
                    voice_rate=options.get("vietsub_dubbing_voice_rate", "+0%"),
                    sub_style=options.get("vietsub_dubbing_sub_style", "default"),
                    original_volume=float(options.get("vietsub_dubbing_original_volume", 0.15)),
                    include_voiceover=True,
                    include_subtitles=True,
                    output_path=output_path,
                    progress_callback=_vs_progress
                )

                if "error" not in vietsub_result and os.path.exists(output_path):
                    has_other_options = False
                    for key, info in VideoProcessor.AVAILABLE_OPTIONS.items():
                        if key in ["vietsub_dubbing", "vietsub_only"]:
                            continue
                        if options.get(key, info.get("default", False)):
                            has_other_options = True
                            break

                    if has_other_options:
                        input_path = output_path
                        output_filename = f"processed_{video_id}_{uuid.uuid4().hex[:6]}.mp4"
                        output_path = os.path.join(settings.PROCESSED_DIR, output_filename)
                        logger.info(f"Vietsub complete. Continuing with other anti-copyright options. New input: {input_path}")
                    else:
                        video_progress[video_id] = 100.0
                        await db.update_video(video_id, {
                            "status": "processed",
                            "processed_path": output_path,
                        })
                        return {"output_path": output_path, "vietsub": True}
                elif "error" in vietsub_result:
                    video_logs[video_id].append(f"❌ Vietsub error: {vietsub_result['error']}")
                    logger.error(f"Vietsub failed: {vietsub_result['error']}, falling back to normal processing")
                    # Fall through to normal processing

            # ─── Vietsub Only (Chỉ Phụ Đề, không lồng tiếng) ───
            if options.get("vietsub_only", False):
                logger.info(f"Vietsub-only (sub only) pipeline triggered for {video_id}")
                from app.services.vietsub_service import full_vietsub_pipeline

                if video_id not in video_logs:
                    video_logs[video_id] = []
                video_progress[video_id] = 0.0

                def _vs_sub_progress(step, msg):
                    video_logs[video_id].append(msg)
                    if step == "extract": video_progress[video_id] = 10.0
                    elif step == "transcribe": video_progress[video_id] = 35.0
                    elif step == "translate": video_progress[video_id] = 60.0
                    elif step == "subtitle": video_progress[video_id] = 75.0
                    elif step == "render": video_progress[video_id] = 95.0

                vietsub_result = await full_vietsub_pipeline(
                    video_path=input_path,
                    sub_style=options.get("vietsub_only_sub_style", "default"),
                    include_voiceover=False,
                    include_subtitles=True,
                    original_volume=1.0,  # Keep original audio at full volume
                    output_path=output_path,
                    progress_callback=_vs_sub_progress,
                )

                if "error" not in vietsub_result and os.path.exists(output_path):
                    has_other_options = False
                    for key, info in VideoProcessor.AVAILABLE_OPTIONS.items():
                        if key in ["vietsub_dubbing", "vietsub_only"]:
                            continue
                        if options.get(key, info.get("default", False)):
                            has_other_options = True
                            break

                    if has_other_options:
                        input_path = output_path
                        output_filename = f"processed_{video_id}_{uuid.uuid4().hex[:6]}.mp4"
                        output_path = os.path.join(settings.PROCESSED_DIR, output_filename)
                        logger.info(f"Vietsub-only complete. Continuing with other anti-copyright options. New input: {input_path}")
                    else:
                        video_progress[video_id] = 100.0
                        await db.update_video(video_id, {
                            "status": "processed",
                            "processed_path": output_path,
                        })
                        return {"output_path": output_path, "vietsub": True}
                elif "error" in vietsub_result:
                    video_logs[video_id].append(f"❌ Vietsub error: {vietsub_result['error']}")
                    logger.error(f"Vietsub-only failed: {vietsub_result['error']}, falling back to normal processing")

            # Build FFmpeg command
            width = video.get("width", 0) or 0
            height = video.get("height", 0) or 0
            video_filters, audio_filters = VideoProcessor.build_filter_complex(
                options, width, height
            )

            # Build command
            cmd = [get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "info", "-stats", "-i", input_path]

            # Add silence at beginning if requested
            add_silence = options.get("add_silence", False)
            silence_duration = float(options.get("silence_value", 0.2))

            # Build filter strings
            vf_str = ",".join(video_filters) if video_filters else None
            af_str = ",".join(audio_filters) if audio_filters else None

            has_watermark = options.get("image_watermark", False)
            storage_dir = os.path.dirname(settings.DOWNLOAD_DIR)
            logo_path = os.path.join(storage_dir, "logo.png")
            
            filter_complex_parts = []
            map_args = []
            
            if has_watermark and os.path.exists(logo_path):
                cmd.extend(["-i", logo_path])
                if vf_str:
                    filter_complex_parts.append(f"[0:v]{vf_str}[base];[base][1:v]overlay=main_w-overlay_w-20:20[v]")
                else:
                    filter_complex_parts.append(f"[0:v][1:v]overlay=main_w-overlay_w-20:20[v]")
                map_args.extend(["-map", "[v]"])
                
                if not options.get("remove_audio", False):
                    if af_str:
                        filter_complex_parts.append(f"[0:a]{af_str}[a]")
                        map_args.extend(["-map", "[a]"])
                    else:
                        map_args.extend(["-map", "0:a?"])
            else:
                if vf_str:
                    cmd.extend(["-vf", vf_str])
                if options.get("remove_audio", False):
                    cmd.extend(["-an"])
                elif af_str:
                    cmd.extend(["-af", af_str])
                    
            if filter_complex_parts:
                cmd.extend(["-filter_complex", ";".join(filter_complex_parts)])
                cmd.extend(map_args)

            # Codec settings
            # Force re-encode if any filters are applied
            force_reencode = bool(vf_str or af_str or options.get("change_fps", False) or (has_watermark and os.path.exists(logo_path)))
            
            if force_reencode or options.get("reencode", True):
                codec = options.get("codec", "libx264")
                crf = int(options.get("crf", 23))
                cmd.extend([
                    "-c:v", codec,
                    "-crf", str(crf),
                    "-preset", "ultrafast",
                    "-tune", "fastdecode",
                    "-threads", "0",
                    "-pix_fmt", "yuv420p",
                ])
                if not options.get("remove_audio", False):
                    cmd.extend(["-c:a", "aac", "-b:a", "192k"])

                # 4. DCT Manipulation (Only valid when re-encoding)
                if options.get("dct_manipulation", False):
                    cmd.extend([
                        "-dct", "faan",
                        "-qmin", "10",
                        "-qmax", "30",
                        "-qdiff", "6",
                        "-g", "30",
                        "-keyint_min", "15",
                        "-bf", "3",
                        "-b_strategy", "2"
                    ])
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
