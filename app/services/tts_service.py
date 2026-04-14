import os
import uuid
import edge_tts
from app.config import settings

VOICES = {
    "vi-VN-HoaiMyNeural": "Nữ Miền Nam",
    "vi-VN-NamMinhNeural": "Nam Miền Bắc",
}

async def generate_speech(text: str, voice: str = "vi-VN-HoaiMyNeural", output_filename: str = None) -> str:
    """
    Generate speech from text using Edge TTS.
    Returns the path to the generated MP3 file.
    """
    if not text.strip():
        return ""
        
    os.makedirs(settings.STORAGE_DIR, exist_ok=True)
    if not output_filename:
        output_filename = f"tts_{uuid.uuid4().hex[:8]}.mp3"
        
    output_path = os.path.join(settings.STORAGE_DIR, output_filename)
    
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)
    
    return output_path
