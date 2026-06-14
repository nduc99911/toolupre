"""
ReupMaster Pro - Vietsub & Lồng Tiếng Service (The Holy Grail)
Full pipeline: Extract Audio → Transcribe (Whisper) → Translate (AI) → TTS (Edge-TTS) → Burn Subtitles + Mix Audio (FFmpeg)
"""
import os
import re
import uuid
import json
import asyncio
import subprocess
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger("reupmaster.vietsub")


def get_ffmpeg() -> str:
    return settings.FFMPEG_PATH if settings.FFMPEG_PATH else "ffmpeg"


def get_ffprobe() -> str:
    ffmpeg = get_ffmpeg()
    return ffmpeg.replace("ffmpeg", "ffprobe") if "ffmpeg" in ffmpeg else "ffprobe"


# ═══════════════════════════════════════════
# STEP 1: Extract Audio from Video
# ═══════════════════════════════════════════
async def extract_audio(video_path: str) -> dict:
    """Extract audio track from video to WAV for Whisper."""
    temp_dir = settings.TEMP_DIR
    os.makedirs(temp_dir, exist_ok=True)
    audio_path = os.path.join(temp_dir, f"audio_{uuid.uuid4().hex[:8]}.wav")

    cmd = [
        get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", video_path,
        "-vn",                    # No video
        "-acodec", "pcm_s16le",   # WAV format for Whisper
        "-ar", "16000",           # 16kHz (Whisper optimal)
        "-ac", "1",               # Mono
        audio_path
    ]

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, timeout=120)
    )

    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")
        return {"error": f"Failed to extract audio: {err}"}

    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 1000:
        return {"error": "Extracted audio file is empty or too small"}

    return {"audio_path": audio_path}


# ═══════════════════════════════════════════
# STEP 2: Transcribe with Whisper (STT)
# ═══════════════════════════════════════════
async def transcribe_audio(audio_path: str, language: str = None) -> dict:
    """
    Transcribe audio using OpenAI Whisper (local model).
    Returns segments with timestamps for subtitle generation.
    """
    try:
        import whisper
    except ImportError:
        return {"error": "openai-whisper not installed. Run: pip install openai-whisper"}

    logger.info(f"Whisper: Transcribing {audio_path} (lang={language or 'auto'})...")

    loop = asyncio.get_event_loop()

    def _transcribe():
        model = whisper.load_model("base")  # base is fast + decent quality
        options = {}
        if language:
            options["language"] = language

        result = model.transcribe(
            audio_path,
            word_timestamps=True,
            verbose=False,
            **options
        )
        return result

    result = await loop.run_in_executor(None, _transcribe)

    detected_lang = result.get("language", "unknown")
    segments = []
    for seg in result.get("segments", []):
        segments.append({
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"].strip(),
        })

    full_text = " ".join(s["text"] for s in segments)
    logger.info(f"Whisper: Detected lang={detected_lang}, {len(segments)} segments, {len(full_text)} chars")

    return {
        "language": detected_lang,
        "segments": segments,
        "full_text": full_text,
    }


# ═══════════════════════════════════════════
# STEP 3: Translate with AI (Gemini/OpenAI)
# ═══════════════════════════════════════════
async def translate_segments(segments: list, source_lang: str = "zh",
                              target_lang: str = "vi") -> dict:
    """
    Translate each subtitle segment using AI.
    Keeps original timing, just replaces text.
    """
    if not segments:
        return {"error": "No segments to translate", "segments": []}

    # Build a batch prompt for efficiency
    texts = [s["text"] for s in segments]
    numbered = "\n".join(f"[{i}] {t}" for i, t in enumerate(texts))

    lang_names = {
        "zh": "Tiếng Trung", "en": "Tiếng Anh", "ja": "Tiếng Nhật",
        "ko": "Tiếng Hàn", "vi": "Tiếng Việt", "th": "Tiếng Thái"
    }
    src_name = lang_names.get(source_lang, source_lang)
    tgt_name = lang_names.get(target_lang, target_lang)

    prompt = f"""Dịch các câu phụ đề sau từ {src_name} sang {tgt_name}.
Giữ nguyên định dạng [số thứ tự]. Chỉ trả về bản dịch, không giải thích.
Dịch tự nhiên, dễ hiểu, phù hợp phụ đề video (ngắn gọn).

{numbered}"""

    try:
        provider = settings.AI_PROVIDER.lower()

        if provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(settings.GEMINI_MODEL)
            response = await asyncio.to_thread(model.generate_content, prompt)
            result_text = response.text

        elif provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": f"You are a professional subtitle translator from {src_name} to {tgt_name}. Translate naturally and concisely for subtitles."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=4000,
            )
            result_text = response.choices[0].message.content
        else:
            return {"error": f"Unknown AI provider: {provider}"}

        # Parse the numbered translations
        translated_segments = []
        translations = {}
        for line in result_text.strip().split("\n"):
            line = line.strip()
            match = re.match(r'\[(\d+)\]\s*(.*)', line)
            if match:
                idx = int(match.group(1))
                translations[idx] = match.group(2).strip()

        for i, seg in enumerate(segments):
            translated_segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "original": seg["text"],
                "text": translations.get(i, seg["text"]),  # Fallback to original
            })

        logger.info(f"Translated {len(translated_segments)} segments ({source_lang} → {target_lang})")
        return {"segments": translated_segments}

    except Exception as e:
        logger.error(f"Translation error: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════
# STEP 4: Generate Vietnamese TTS Audio
# ═══════════════════════════════════════════
# Professional narrator-style: Group sentences into paragraphs,
# generate each paragraph as one continuous TTS call for natural
# intonation, then place paragraphs on the timeline with proper pacing.

async def _get_audio_duration(file_path: str) -> float:
    """Get duration of an audio file in seconds using ffprobe."""
    cmd = [
        get_ffprobe(), "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        file_path
    ]
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, timeout=10)
    )
    try:
        return float(result.stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0


async def _adjust_clip_speed(input_path: str, output_path: str, speed: float) -> bool:
    """Adjust speed of an audio clip using FFmpeg atempo (capped at 1.25x)."""
    speed = max(0.85, min(speed, 1.25))
    if abs(speed - 1.0) < 0.03:
        return False  # No meaningful change needed
    cmd = [
        get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-i", input_path,
        "-af", f"atempo={speed:.3f}",
        "-codec:a", "libmp3lame", "-q:a", "2",
        output_path
    ]
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, timeout=30)
    )
    return result.returncode == 0


def _group_segments_into_paragraphs(segments: list, max_gap: float = 2.0,
                                     max_sentences: int = 6) -> list:
    """
    Group subtitle segments into natural paragraphs for narration.
    Groups by proximity (gap < max_gap seconds) and limits per group.
    Returns list of paragraph dicts with combined text and time range.
    """
    if not segments:
        return []

    paragraphs = []
    current_group = [segments[0]]

    for i in range(1, len(segments)):
        seg = segments[i]
        prev = current_group[-1]
        gap = seg["start"] - prev["end"]

        # Start new paragraph if gap is large or group is big enough
        if gap > max_gap or len(current_group) >= max_sentences:
            paragraphs.append(_make_paragraph(current_group))
            current_group = [seg]
        else:
            current_group.append(seg)

    if current_group:
        paragraphs.append(_make_paragraph(current_group))

    return paragraphs


def _make_paragraph(segs: list) -> dict:
    """Combine a group of segments into a single paragraph."""
    # Join texts with punctuation-aware spacing
    texts = []
    for s in segs:
        t = s.get("text", "").strip()
        if t:
            # Add period if sentence doesn't end with punctuation
            if t[-1] not in ".!?。，,;:：":
                t += "."
            texts.append(t)

    combined_text = " ".join(texts)
    return {
        "start": segs[0]["start"],
        "end": segs[-1]["end"],
        "text": combined_text,
        "sentence_count": len(segs),
    }


async def generate_voiceover(segments: list, voice_id: str = "vi-female",
                              rate: str = "+0%") -> dict:
    """
    Generate Vietnamese voiceover using professional narrator style.

    Instead of 100+ individual clips, groups segments into ~15-20 paragraphs.
    Each paragraph is generated as ONE TTS call, giving Edge-TTS full context
    for natural intonation and pacing. Speed is kept consistent across all
    paragraphs for a smooth, professional dubbing feel.
    """
    try:
        import edge_tts
    except ImportError:
        return {"error": "edge-tts not installed"}

    from app.services.tts_service import VOICES

    voice_name = VOICES.get(voice_id, VOICES["vi-female"])
    temp_dir = settings.TEMP_DIR
    os.makedirs(temp_dir, exist_ok=True)

    uid = uuid.uuid4().hex[:6]
    clips_dir = os.path.join(temp_dir, f"tts_clips_{uid}")
    os.makedirs(clips_dir, exist_ok=True)

    # ── Step A: Group segments into paragraphs ──
    paragraphs = _group_segments_into_paragraphs(segments)
    logger.info(f"Voiceover: {len(segments)} segments → {len(paragraphs)} paragraphs")

    # ── Step B: Generate TTS for each paragraph ──
    # Use a slightly faster base rate for dubbing feel
    base_rate = "+12%"  # Consistent slightly-fast narration speed
    paragraph_clips = []

    for i, para in enumerate(paragraphs):
        clip_path = os.path.join(clips_dir, f"para_{i:03d}.mp3")
        try:
            communicate = edge_tts.Communicate(
                text=para["text"],
                voice=voice_name,
                rate=base_rate,
            )
            await communicate.save(clip_path)

            if os.path.exists(clip_path) and os.path.getsize(clip_path) > 100:
                clip_duration = await _get_audio_duration(clip_path)
                paragraph_clips.append({
                    "start": para["start"],
                    "end": para["end"],
                    "clip": clip_path,
                    "text": para["text"],
                    "clip_duration": clip_duration,
                    "slot_duration": para["end"] - para["start"],
                })
        except Exception as e:
            logger.warning(f"TTS paragraph {i} failed: {e}")

    if not paragraph_clips:
        return {"error": "No TTS paragraphs generated"}

    # ── Step C: Gentle speed adjustment (max 1.25x, keep it natural) ──
    for i, pc in enumerate(paragraph_clips):
        if pc["clip_duration"] <= 0:
            continue

        # Calculate available time slot
        if i + 1 < len(paragraph_clips):
            available = paragraph_clips[i + 1]["start"] - pc["start"] - 0.3
        else:
            available = pc["slot_duration"] + 1.5

        available = max(available, 1.0)

        if pc["clip_duration"] > available:
            speed_needed = pc["clip_duration"] / available
            # Cap at 1.25x to keep it sounding natural
            speed_needed = min(speed_needed, 1.25)
            if speed_needed > 1.05:
                sped_path = pc["clip"].replace(".mp3", "_adj.mp3")
                success = await _adjust_clip_speed(pc["clip"], sped_path, speed_needed)
                if success and os.path.exists(sped_path):
                    pc["clip"] = sped_path
                    logger.info(f"Para {i}: adjusted {speed_needed:.2f}x")

    # ── Step D: Merge into single voiceover track ──
    merged_path = os.path.join(temp_dir, f"voiceover_{uid}.mp3")
    result = await _merge_tts_clips(paragraph_clips, merged_path)

    if "error" in result:
        return result

    logger.info(f"Voiceover complete: {len(paragraph_clips)} paragraphs → {merged_path}")
    return {
        "audio_path": merged_path,
        "clips_dir": clips_dir,
        "clip_count": len(paragraph_clips),
        "segments": paragraph_clips,
    }


async def _merge_tts_clips(segments: list, output_path: str) -> dict:
    """Merge paragraph TTS clips into a single audio file with correct timing."""
    if not segments:
        return {"error": "No segments to merge"}

    # Get total duration from last segment
    total_duration = max(s["end"] for s in segments) + 2.0

    filter_parts = []

    # Create a silent base track (input 0)
    filter_parts.append(
        f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={total_duration}[base]"
    )

    for i, seg in enumerate(segments):
        delay_ms = int(seg["start"] * 1000)
        filter_parts.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms}[d{i}]")

    # Mix all delayed clips with the silent base
    mix_inputs = "[base]" + "".join(f"[d{i}]" for i in range(len(segments)))
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(segments)+1}:normalize=0:dropout_transition=0[out]"
    )

    filter_str = ";".join(filter_parts)

    cmd = [
        get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i",
        f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={total_duration}",
    ]
    for seg in segments:
        cmd.extend(["-i", seg["clip"]])

    cmd.extend([
        "-filter_complex", filter_str,
        "-map", "[out]",
        "-codec:a", "libmp3lame", "-q:a", "2",
        "-t", str(total_duration),
        output_path
    ])

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, timeout=300)
    )

    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")
        logger.error(f"FFmpeg merge error: {err}")
        return {"error": f"Failed to merge TTS clips: {err}"}

    return {"audio_path": output_path}


# ═══════════════════════════════════════════
# STEP 5: Build SRT Subtitle File
# ═══════════════════════════════════════════
def build_srt(segments: list, include_original: bool = False) -> str:
    """Build SRT subtitle content from translated segments."""
    srt_lines = []
    for i, seg in enumerate(segments, 1):
        start = _seconds_to_srt(seg["start"])
        end = _seconds_to_srt(seg["end"])

        text = seg.get("text", "")
        if include_original and seg.get("original"):
            text = f"{text}\n{seg['original']}"

        srt_lines.append(f"{i}")
        srt_lines.append(f"{start} --> {end}")
        srt_lines.append(text)
        srt_lines.append("")

    return "\n".join(srt_lines)


def _seconds_to_srt(seconds: float) -> str:
    """Convert seconds to SRT time format HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ═══════════════════════════════════════════
# STEP 6: Final Render - Burn Subs + Mix Audio
# ═══════════════════════════════════════════
async def render_final_video(
    video_path: str,
    srt_path: str,
    voiceover_path: str = None,
    output_path: str = None,
    original_volume: float = 0.0,
    voiceover_volume: float = 1.0,
    sub_style: str = "default",
) -> dict:
    """
    Final render: burn subtitles onto video and optionally mix voiceover audio.

    Args:
        video_path: Path to input video
        srt_path: Path to SRT subtitle file
        voiceover_path: Path to Vietnamese voiceover audio (optional)
        output_path: Custom output path (auto-generated if None)
        original_volume: Volume of original audio (0.0 = mute, 1.0 = full)
        voiceover_volume: Volume of voiceover audio
        sub_style: Subtitle style preset
    """
    if not output_path:
        uid = uuid.uuid4().hex[:6]
        output_path = os.path.join(settings.PROCESSED_DIR, f"vietsub_{uid}.mp4")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Subtitle style presets
    styles = {
        "default": "FontName=Arial,FontSize=12,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=2,Shadow=1,MarginV=30",
        "modern": "FontName=Roboto,FontSize=14,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,Outline=2,Shadow=0,MarginV=25,Bold=1",
        "cinematic": "FontName=Georgia,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H00333333,Outline=3,Shadow=2,MarginV=40",
        "tiktok": "FontName=Arial,FontSize=16,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,Outline=3,Shadow=0,MarginV=20,Bold=1",
    }
    style_str = styles.get(sub_style, styles["default"])

    # Escape the SRT path for FFmpeg (Windows backslashes need special handling)
    srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")

    # Build FFmpeg command
    cmd = [get_ffmpeg(), "-y", "-hide_banner", "-loglevel", "info", "-stats"]
    cmd.extend(["-i", video_path])

    if voiceover_path and os.path.exists(voiceover_path):
        cmd.extend(["-i", voiceover_path])

        # Complex filter: burn subs + replace/mix audio
        filter_parts = []

        # Subtitle filter on video
        filter_parts.append(
            f"[0:v]subtitles='{srt_escaped}':force_style='{style_str}'[subv]"
        )

        if original_volume <= 0.01:
            # Completely mute original audio, use only voiceover
            filter_parts.append(
                f"[1:a]volume={voiceover_volume}[final_a]"
            )
            map_audio = "[final_a]"
        else:
            # Mix: reduce original + add voiceover
            filter_parts.append(
                f"[0:a]volume={original_volume}[orig_a]"
            )
            filter_parts.append(
                f"[1:a]volume={voiceover_volume}[vo_a]"
            )
            filter_parts.append(
                "[orig_a][vo_a]amix=inputs=2:duration=first:dropout_transition=2[final_a]"
            )
            map_audio = "[final_a]"

        filter_str = ";".join(filter_parts)
        cmd.extend([
            "-filter_complex", filter_str,
            "-map", "[subv]", "-map", map_audio,
        ])
    else:
        # Only burn subtitles, keep original audio
        cmd.extend([
            "-vf", f"subtitles='{srt_escaped}':force_style='{style_str}'",
            "-c:a", "copy",
        ])

    # Output settings
    cmd.extend([
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-movflags", "+faststart",
        output_path
    ])

    logger.info(f"Rendering Vietsub video: {video_path} → {output_path}")

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(cmd, capture_output=True, timeout=900)
    )

    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")
        logger.error(f"Render error: {err[-500:]}")
        return {"error": f"FFmpeg render failed: {err[-300:]}"}

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
        return {"error": "Output video file is empty"}

    logger.info(f"Vietsub render complete: {output_path}")
    return {
        "output_path": output_path,
        "file_size": os.path.getsize(output_path),
    }


# ═══════════════════════════════════════════
# MASTER PIPELINE: Full Vietsub + Lồng Tiếng
# ═══════════════════════════════════════════
async def full_vietsub_pipeline(
    video_path: str,
    source_lang: str = None,
    target_lang: str = "vi",
    voice_id: str = "vi-female",
    voice_rate: str = "+0%",
    include_voiceover: bool = True,
    include_subtitles: bool = True,
    include_original_sub: bool = False,
    original_volume: float = 0.0,
    sub_style: str = "default",
    output_path: str = None,
    progress_callback=None,
) -> dict:
    """
    Full automatic Vietsub + Lồng Tiếng pipeline.

    Pipeline:
    1. Extract audio from video
    2. Transcribe with Whisper (detect language auto)
    3. Translate segments to Vietnamese with AI
    4. Generate Vietnamese voiceover with Edge-TTS
    5. Build SRT subtitle file
    6. Burn subtitles + mix audio with FFmpeg

    Returns dict with output_path and metadata.
    """
    temp_dir = settings.TEMP_DIR
    os.makedirs(temp_dir, exist_ok=True)
    uid = uuid.uuid4().hex[:6]

    result_meta = {
        "steps": {},
        "source_lang": None,
        "segment_count": 0,
    }

    def _update(step, msg):
        result_meta["steps"][step] = msg
        if progress_callback:
            progress_callback(step, msg)
        logger.info(f"[Vietsub] {step}: {msg}")

    try:
        # ── Step 1: Extract Audio ──
        _update("extract", "Đang tách âm thanh từ video...")
        audio_result = await extract_audio(video_path)
        if "error" in audio_result:
            return {**result_meta, "error": f"Step 1 (Extract): {audio_result['error']}"}
        audio_path = audio_result["audio_path"]
        _update("extract", "✅ Tách âm thanh thành công")

        # ── Step 2: Transcribe ──
        _update("transcribe", "Đang nhận dạng giọng nói (Whisper AI)...")
        transcribe_result = await transcribe_audio(audio_path, language=source_lang)
        if "error" in transcribe_result:
            return {**result_meta, "error": f"Step 2 (Transcribe): {transcribe_result['error']}"}

        segments = transcribe_result["segments"]
        detected_lang = transcribe_result["language"]
        result_meta["source_lang"] = detected_lang
        result_meta["segment_count"] = len(segments)

        if not segments:
            return {**result_meta, "error": "Không tìm thấy lời nói trong video"}

        _update("transcribe", f"✅ Nhận dạng thành công ({detected_lang}, {len(segments)} câu)")

        # ── Step 3: Translate ──
        if detected_lang == target_lang:
            _update("translate", "⏭️ Ngôn ngữ gốc trùng mục tiêu, bỏ qua dịch")
            translated = [{"start": s["start"], "end": s["end"], "text": s["text"], "original": s["text"]} for s in segments]
        else:
            _update("translate", f"Đang dịch {detected_lang} → {target_lang} bằng AI...")
            translate_result = await translate_segments(segments, source_lang=detected_lang, target_lang=target_lang)
            if "error" in translate_result:
                return {**result_meta, "error": f"Step 3 (Translate): {translate_result['error']}"}
            translated = translate_result["segments"]
            _update("translate", f"✅ Dịch xong {len(translated)} câu")

        # ── Step 4: Build SRT ──
        srt_path = None
        if include_subtitles:
            _update("subtitle", "Đang tạo file phụ đề SRT...")
            srt_content = build_srt(translated, include_original=include_original_sub)
            srt_path = os.path.join(temp_dir, f"vietsub_{uid}.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            _update("subtitle", f"✅ Phụ đề SRT: {len(translated)} dòng")

        # ── Step 5: Generate Voiceover ──
        voiceover_path = None
        if include_voiceover:
            _update("voiceover", f"Đang lồng tiếng Việt ({voice_id})...")
            vo_result = await generate_voiceover(translated, voice_id=voice_id, rate=voice_rate)
            if "error" in vo_result:
                _update("voiceover", f"⚠️ Lồng tiếng thất bại: {vo_result['error']}")
                # Continue without voiceover
            else:
                voiceover_path = vo_result["audio_path"]
                _update("voiceover", f"✅ Lồng tiếng xong ({vo_result['clip_count']} đoạn)")

        # ── Step 6: Final Render ──
        if not srt_path and not voiceover_path:
            return {**result_meta, "error": "Không có phụ đề lẫn lồng tiếng để render"}

        _update("render", "Đang render video cuối cùng (FFmpeg)...")
        render_result = await render_final_video(
            video_path=video_path,
            srt_path=srt_path,
            voiceover_path=voiceover_path,
            output_path=output_path,
            original_volume=original_volume,
            sub_style=sub_style,
        )

        if "error" in render_result:
            return {**result_meta, "error": f"Step 6 (Render): {render_result['error']}"}

        _update("render", "✅ Render hoàn tất!")

        # Cleanup temp audio
        try:
            os.remove(audio_path)
        except:
            pass

        return {
            **result_meta,
            "output_path": render_result["output_path"],
            "srt_path": srt_path,
            "voiceover_path": voiceover_path,
            "file_size": render_result["file_size"],
        }

    except Exception as e:
        logger.error(f"Vietsub pipeline error: {e}")
        return {**result_meta, "error": str(e)}
