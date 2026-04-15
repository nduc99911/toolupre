"""
ReupMaster Pro - TTS (Text-to-Speech) Service
Generates AI voiceover using Microsoft Edge-TTS.
Free, high-quality multilingual voices.
"""
import os
import asyncio
import logging
import uuid
from pathlib import Path

from app.config import settings

logger = logging.getLogger("reupmaster.tts")


# ─── Available Voices ───
VOICES = {
    # Vietnamese
    "vi-female": "vi-VN-HoaiMyNeural",
    "vi-male": "vi-VN-NamMinhNeural",
    # English
    "en-female": "en-US-JennyNeural",
    "en-male": "en-US-GuyNeural",
    "en-female-2": "en-US-AriaNeural",
    # Chinese
    "zh-female": "zh-CN-XiaoxiaoNeural",
    "zh-male": "zh-CN-YunxiNeural",
    # Korean
    "ko-female": "ko-KR-SunHiNeural",
    "ko-male": "ko-KR-InJoonNeural",
    # Japanese
    "ja-female": "ja-JP-NanamiNeural",
    "ja-male": "ja-JP-KeitaNeural",
    # Thai
    "th-female": "th-TH-PremwadeeNeural",
    "th-male": "th-TH-NiwatNeural",
}

VOICE_LIST = [
    {"id": k, "name": v, "lang": k.split("-")[0], "gender": k.split("-")[1]}
    for k, v in VOICES.items()
]


async def generate_tts(
    text: str,
    voice_id: str = "vi-female",
    rate: str = "+0%",
    pitch: str = "+0Hz",
    volume: str = "+0%",
) -> dict:
    """
    Generate speech audio from text using Edge-TTS.

    Args:
        text: The text to convert to speech
        voice_id: One of the keys from VOICES dict
        rate: Speed adjustment (e.g., "+10%", "-5%")
        pitch: Pitch adjustment (e.g., "+5Hz", "-3Hz")
        volume: Volume adjustment

    Returns:
        dict with 'audio_path' on success or 'error' on failure
    """
    try:
        import edge_tts
    except ImportError:
        return {"error": "edge-tts not installed. Run: pip install edge-tts"}

    voice_name = VOICES.get(voice_id, VOICES["vi-female"])
    temp_dir = settings.TEMP_DIR
    os.makedirs(temp_dir, exist_ok=True)

    output_file = os.path.join(temp_dir, f"tts_{uuid.uuid4().hex[:8]}.mp3")

    try:
        logger.info(f"TTS: Generating voice '{voice_name}' for {len(text)} chars")

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice_name,
            rate=rate,
            pitch=pitch,
            volume=volume,
        )
        await communicate.save(output_file)

        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            logger.info(f"TTS: Audio saved -> {output_file}")
            return {
                "audio_path": output_file,
                "voice": voice_name,
                "duration_estimate": len(text) * 0.08,  # rough estimate
            }
        else:
            return {"error": "TTS generated empty audio file"}

    except Exception as e:
        logger.error(f"TTS error: {e}")
        return {"error": str(e)}


async def generate_tts_with_subtitles(
    text: str,
    voice_id: str = "vi-female",
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> dict:
    """
    Generate TTS audio AND an SRT subtitle file with word-level timing.
    Edge-TTS provides word boundary events we can use for subtitles.
    """
    try:
        import edge_tts
    except ImportError:
        return {"error": "edge-tts not installed"}

    voice_name = VOICES.get(voice_id, VOICES["vi-female"])
    temp_dir = settings.TEMP_DIR
    os.makedirs(temp_dir, exist_ok=True)

    uid = uuid.uuid4().hex[:8]
    audio_path = os.path.join(temp_dir, f"tts_{uid}.mp3")
    srt_path = os.path.join(temp_dir, f"tts_{uid}.srt")

    try:
        communicate = edge_tts.Communicate(
            text=text,
            voice=voice_name,
            rate=rate,
            pitch=pitch,
        )

        # Collect word boundaries for subtitle generation
        word_boundaries = []

        async def collect_and_save():
            with open(audio_path, "wb") as audio_file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        word_boundaries.append({
                            "offset": chunk["offset"],        # microseconds
                            "duration": chunk["duration"],     # microseconds
                            "text": chunk["text"],
                        })

        await collect_and_save()

        # Build SRT from word boundaries (group words into subtitle segments)
        srt_content = _build_srt_from_boundaries(word_boundaries, words_per_line=8)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        logger.info(f"TTS+Sub: audio={audio_path}, srt={srt_path}, {len(word_boundaries)} words")

        return {
            "audio_path": audio_path,
            "srt_path": srt_path,
            "voice": voice_name,
            "word_count": len(word_boundaries),
        }

    except Exception as e:
        logger.error(f"TTS+Sub error: {e}")
        return {"error": str(e)}


def _build_srt_from_boundaries(boundaries: list, words_per_line: int = 8) -> str:
    """Build SRT subtitle content from Edge-TTS word boundary events."""
    if not boundaries:
        return ""

    srt_lines = []
    index = 1
    i = 0

    while i < len(boundaries):
        # Group N words per subtitle line
        chunk = boundaries[i: i + words_per_line]
        start_us = chunk[0]["offset"]
        end_us = chunk[-1]["offset"] + chunk[-1]["duration"]
        text = " ".join(w["text"] for w in chunk)

        start_time = _us_to_srt_time(start_us)
        end_time = _us_to_srt_time(end_us)

        srt_lines.append(f"{index}")
        srt_lines.append(f"{start_time} --> {end_time}")
        srt_lines.append(text)
        srt_lines.append("")

        index += 1
        i += words_per_line

    return "\n".join(srt_lines)


def _us_to_srt_time(microseconds: int) -> str:
    """Convert microseconds to SRT time format: HH:MM:SS,mmm"""
    # Edge-TTS gives offset in 100ns units (ticks), convert to ms
    ms = microseconds / 10000
    total_seconds = ms / 1000
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    millis = int(ms % 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


async def list_voices(language: str = None) -> list:
    """List available Edge-TTS voices, optionally filtered by language."""
    try:
        import edge_tts
        voices = await edge_tts.list_voices()
        if language:
            voices = [v for v in voices if v["Locale"].startswith(language)]
        return [
            {
                "name": v["ShortName"],
                "locale": v["Locale"],
                "gender": v["Gender"],
                "friendly_name": v.get("FriendlyName", ""),
            }
            for v in voices
        ]
    except Exception as e:
        return [{"error": str(e)}]
