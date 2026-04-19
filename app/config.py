"""
ReupMaster Pro - Configuration Module
Loads settings from .env file and provides defaults.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Gemini
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"

    # AI Provider
    AI_PROVIDER: str = "gemini"  # "openai" or "gemini"

    # Facebook
    FB_APP_ID: str = ""
    FB_APP_SECRET: str = ""

    # FFmpeg
    FFMPEG_PATH: str = ""

    # Cleanup
    AUTO_CLEANUP_VIDEO: bool = False

    # Storage paths
    DOWNLOAD_DIR: str = str(BASE_DIR / "storage" / "downloads")
    PROCESSED_DIR: str = str(BASE_DIR / "storage" / "processed")
    TEMP_DIR: str = str(BASE_DIR / "storage" / "temp")

    # Database
    DATABASE_URL: str = str(BASE_DIR / "storage" / "reupmaster.db")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def ensure_dirs(self):
        """Create storage directories if they don't exist."""
        for dir_path in [self.DOWNLOAD_DIR, self.PROCESSED_DIR, self.TEMP_DIR]:
            os.makedirs(dir_path, exist_ok=True)
        # Also ensure database directory exists
        os.makedirs(os.path.dirname(self.DATABASE_URL), exist_ok=True)


settings = Settings()
settings.ensure_dirs()
