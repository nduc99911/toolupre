import os
import subprocess
import logging
import time
import httpx
from app.config import settings

logger = logging.getLogger("reupmaster.douyin_service")

class DouyinService:
    def __init__(self):
        self.process = None
        self.api_url = "http://localhost:3000"

    def start(self):
        douyin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "douyin_api"))
        if not os.path.exists(douyin_dir):
            logger.error(f"douyin_api directory not found at {douyin_dir}")
            return

        logger.info(f"Starting Douyin API Server from {douyin_dir}")
        try:
            self.process = subprocess.Popen(
                "node server.js",
                cwd=douyin_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                shell=True
            )
            logger.info("Douyin API Server started on port 3000")
        except Exception as e:
            logger.error(f"Failed to start Douyin API Server: {e}")

    def stop(self):
        if self.process:
            logger.info("Stopping Douyin API Server")
            self.process.terminate()
            self.process = None

    async def get_video_info(self, url: str) -> dict:
        """Fetch video info via local node server"""
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{self.api_url}/api/parse", json={"url": url})
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"API returned {resp.status_code}: {resp.text}"}
        except Exception as e:
            logger.error(f"Error fetching douyin video info: {e}")
            return {"error": str(e)}

    async def get_profile(self, url: str, count: int = 10) -> dict:
        """Fetch profile videos via local node server"""
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(f"{self.api_url}/api/profile", json={"url": url, "count": count})
                if resp.status_code == 200:
                    return resp.json()
                return {"error": f"API returned {resp.status_code}: {resp.text}"}
        except Exception as e:
            logger.error(f"Error fetching douyin profile: {e}")
            return {"error": str(e)}

douyin_service = DouyinService()

# --- Aliases for douyin_router.py compatibility ---
async def fetch_video_info(url: str):
    return await douyin_service.get_video_info(url)

async def fetch_profile_videos(url: str, max_count: int = 10):
    return await douyin_service.get_profile(url, max_count)

async def download_douyin_video_task(url: str, video_id: str, direct_url: str = None):
    from app.services.downloader import _download_douyin
    from app import database as db
    try:
        res = await _download_douyin(url, video_id, direct_url)
        if res and "error" in res:
            await db.update_video(video_id, {"status": "failed", "error_message": res["error"]})
        return res
    except Exception as e:
        import traceback
        traceback.print_exc()
        await db.update_video(video_id, {"status": "failed", "error_message": str(e)})

