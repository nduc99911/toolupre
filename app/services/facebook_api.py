"""
ReupMaster Pro - Facebook Graph API Service
Handles Facebook Page authentication, posting, and scheduling.
"""
import os
import json
import httpx
import asyncio
from datetime import datetime, timedelta

from app.config import settings
from app import database as db

FB_GRAPH_URL = "https://graph.facebook.com/v21.0"


class FacebookAPI:
    """Facebook Graph API wrapper for Page management and posting."""

    @staticmethod
    async def verify_token(access_token: str) -> dict:
        """Verify a page access token and get page info."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Debug token
            response = await client.get(
                f"{FB_GRAPH_URL}/me",
                params={
                    "access_token": access_token,
                    "fields": "id,name,category,fan_count,followers_count"
                }
            )
            data = response.json()

            if "error" in data:
                return {"error": data["error"]["message"]}

            return {
                "page_id": data.get("id"),
                "page_name": data.get("name"),
                "category": data.get("category", ""),
                "fan_count": data.get("fan_count", 0),
                "followers_count": data.get("followers_count", 0),
                "valid": True
            }

    @staticmethod
    async def get_user_pages(user_access_token: str) -> list[dict]:
        """Get all pages managed by a user."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{FB_GRAPH_URL}/me/accounts",
                params={
                    "access_token": user_access_token,
                    "fields": "id,name,access_token,category,fan_count"
                }
            )
            data = response.json()

            if "error" in data:
                return [{"error": data["error"]["message"]}]

            pages = []
            for page in data.get("data", []):
                pages.append({
                    "page_id": page["id"],
                    "page_name": page.get("name", ""),
                    "access_token": page.get("access_token", ""),
                    "category": page.get("category", ""),
                    "fan_count": page.get("fan_count", 0),
                })

            return pages

    @staticmethod
    async def post_video(page_id: str, access_token: str,
                         video_path: str, caption: str = "",
                         title: str = "") -> dict:
        """
        Upload and publish a video to a Facebook Page.
        Uses resumable upload for large files.
        """
        if not os.path.exists(video_path):
            return {"error": f"Video file not found: {video_path}"}

        file_size = os.path.getsize(video_path)

        # For files under 1GB, use simple upload
        if file_size < 1_000_000_000:
            return await FacebookAPI._simple_video_upload(
                page_id, access_token, video_path, caption, title
            )
        else:
            return await FacebookAPI._resumable_video_upload(
                page_id, access_token, video_path, caption, title
            )

    @staticmethod
    async def _simple_video_upload(page_id: str, access_token: str,
                                    video_path: str, caption: str,
                                    title: str) -> dict:
        """Simple video upload for files under 1GB."""
        async with httpx.AsyncClient(timeout=600) as client:
            with open(video_path, "rb") as video_file:
                files = {
                    "source": (os.path.basename(video_path), video_file, "video/mp4")
                }
                data = {
                    "access_token": access_token,
                    "description": caption,
                    "title": title or "",
                }

                response = await client.post(
                    f"{FB_GRAPH_URL}/{page_id}/videos",
                    files=files,
                    data=data,
                )

            result = response.json()

            if "error" in result:
                return {"error": result["error"]["message"]}

            return {
                "success": True,
                "post_id": result.get("id", ""),
                "message": "Video published successfully!"
            }

    @staticmethod
    async def _resumable_video_upload(page_id: str, access_token: str,
                                       video_path: str, caption: str,
                                       title: str) -> dict:
        """Resumable video upload for large files."""
        file_size = os.path.getsize(video_path)

        async with httpx.AsyncClient(timeout=600) as client:
            # Step 1: Initialize upload
            init_response = await client.post(
                f"{FB_GRAPH_URL}/{page_id}/videos",
                data={
                    "access_token": access_token,
                    "upload_phase": "start",
                    "file_size": str(file_size),
                }
            )
            init_data = init_response.json()

            if "error" in init_data:
                return {"error": init_data["error"]["message"]}

            upload_session_id = init_data.get("upload_session_id")
            video_id = init_data.get("video_id")

            # Step 2: Transfer chunks
            chunk_size = 4 * 1024 * 1024  # 4MB chunks
            offset = 0

            with open(video_path, "rb") as f:
                while offset < file_size:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break

                    transfer_response = await client.post(
                        f"{FB_GRAPH_URL}/{page_id}/videos",
                        files={
                            "video_file_chunk": (
                                os.path.basename(video_path),
                                chunk,
                                "video/mp4"
                            )
                        },
                        data={
                            "access_token": access_token,
                            "upload_phase": "transfer",
                            "upload_session_id": upload_session_id,
                            "start_offset": str(offset),
                        }
                    )
                    transfer_data = transfer_response.json()

                    if "error" in transfer_data:
                        return {"error": transfer_data["error"]["message"]}

                    offset = int(transfer_data.get("start_offset", file_size))

            # Step 3: Finish upload
            finish_response = await client.post(
                f"{FB_GRAPH_URL}/{page_id}/videos",
                data={
                    "access_token": access_token,
                    "upload_phase": "finish",
                    "upload_session_id": upload_session_id,
                    "title": title or "",
                    "description": caption,
                }
            )
            finish_data = finish_response.json()

            if "error" in finish_data:
                return {"error": finish_data["error"]["message"]}

            return {
                "success": True,
                "post_id": video_id,
                "message": "Video published successfully (resumable upload)"
            }

    @staticmethod
    async def schedule_video(page_id: str, access_token: str,
                             video_path: str, caption: str, title: str,
                             scheduled_time: datetime) -> dict:
        """Schedule a video post for later publication."""
        if not os.path.exists(video_path):
            return {"error": f"Video file not found: {video_path}"}

        # Facebook requires scheduled_publish_time as Unix timestamp
        # Must be between 10 minutes and 6 months from now
        timestamp = int(scheduled_time.timestamp())

        async with httpx.AsyncClient(timeout=600) as client:
            with open(video_path, "rb") as video_file:
                files = {
                    "source": (os.path.basename(video_path), video_file, "video/mp4")
                }
                data = {
                    "access_token": access_token,
                    "description": caption,
                    "title": title or "",
                    "published": "false",
                    "scheduled_publish_time": str(timestamp),
                }

                response = await client.post(
                    f"{FB_GRAPH_URL}/{page_id}/videos",
                    files=files,
                    data=data,
                )

            result = response.json()

            if "error" in result:
                return {"error": result["error"]["message"]}

            return {
                "success": True,
                "post_id": result.get("id", ""),
                "scheduled_time": scheduled_time.isoformat(),
                "message": f"Video scheduled for {scheduled_time.strftime('%d/%m/%Y %H:%M')}"
            }

    @staticmethod
    async def post_text(page_id: str, access_token: str,
                        message: str, link: str = "") -> dict:
        """Post a text/link to a Facebook Page."""
        async with httpx.AsyncClient(timeout=30) as client:
            data = {
                "access_token": access_token,
                "message": message,
            }
            if link:
                data["link"] = link

            response = await client.post(
                f"{FB_GRAPH_URL}/{page_id}/feed",
                data=data,
            )
            result = response.json()

            if "error" in result:
                return {"error": result["error"]["message"]}

            return {
                "success": True,
                "post_id": result.get("id", ""),
                "message": "Post published successfully!"
            }

    @staticmethod
    async def get_page_posts(page_id: str, access_token: str,
                             limit: int = 10) -> list[dict]:
        """Get recent posts from a page."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{FB_GRAPH_URL}/{page_id}/posts",
                params={
                    "access_token": access_token,
                    "fields": "id,message,created_time,type,permalink_url",
                    "limit": limit,
                }
            )
            data = response.json()

            if "error" in data:
                return [{"error": data["error"]["message"]}]

            return data.get("data", [])

    @staticmethod
    async def delete_post(post_id: str, access_token: str) -> dict:
        """Delete a post."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(
                f"{FB_GRAPH_URL}/{post_id}",
                params={"access_token": access_token}
            )
            data = response.json()

            if "error" in data:
                return {"error": data["error"]["message"]}

            return {"success": True, "message": "Post deleted successfully"}
