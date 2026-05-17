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
import logging

logger = logging.getLogger("reupmaster.fbapi")

FB_GRAPH_URL = "https://graph.facebook.com/v21.0"


class FacebookAPI:
    """Facebook Graph API wrapper for Page management and posting."""

    @staticmethod
    async def extend_token(short_token: str) -> str:
        """Exchange short-lived token for long-lived token (60 days)."""
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(
                    "https://graph.facebook.com/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": settings.FB_APP_ID,
                        "client_secret": settings.FB_APP_SECRET,
                        "fb_exchange_token": short_token
                    }
                )
                data = response.json()
                return data.get("access_token", short_token)
            except Exception as e:
                logger.error(f"Failed to extend token: {e}")
                return short_token

    @staticmethod
    async def get_token_info(access_token: str) -> dict:
        """Get detailed info about a token (expiry, permissions, etc)."""
        # Requires app access token or user token for some fields
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                response = await client.get(
                    "https://graph.facebook.com/debug_token",
                    params={
                        "input_token": access_token,
                        "access_token": f"{settings.FB_APP_ID}|{settings.FB_APP_SECRET}"
                    }
                )
                return response.json().get("data", {})
            except Exception as e:
                logger.error(f"Failed to debug token: {e}")
                return {"error": str(e)}

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

        # For files under 10MB, use simple upload to avoid HTTP 413 Request Entity Too Large
        if file_size < 10_000_000:
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
                                    title: str, scheduled_publish_time: str = None) -> dict:
        """Simple video upload for files under 10MB."""
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
                if scheduled_publish_time:
                    data["published"] = "false"
                    data["scheduled_publish_time"] = scheduled_publish_time

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
                                       title: str, scheduled_publish_time: str = None) -> dict:
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
            data = {
                "access_token": access_token,
                "upload_phase": "finish",
                "upload_session_id": upload_session_id,
                "title": title or "",
                "description": caption,
            }
            if scheduled_publish_time:
                data["published"] = "false"
                data["scheduled_publish_time"] = scheduled_publish_time

            finish_response = await client.post(
                f"{FB_GRAPH_URL}/{page_id}/videos",
                data=data
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

        file_size = os.path.getsize(video_path)

        # Facebook requires scheduled_publish_time as Unix timestamp
        # Must be between 10 minutes and 6 months from now
        timestamp = str(int(scheduled_time.timestamp()))

        if file_size < 10_000_000:
            result = await FacebookAPI._simple_video_upload(
                page_id, access_token, video_path, caption, title, timestamp
            )
        else:
            result = await FacebookAPI._resumable_video_upload(
                page_id, access_token, video_path, caption, title, timestamp
            )

        if "error" in result:
            return result
        
        return {
            "success": True,
            "post_id": result.get("post_id", ""),
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

    @staticmethod
    async def exchange_code_for_token(code: str, redirect_uri: str) -> str:
        """Exchange OAuth code for a short-lived user access token."""
        from app.config import settings
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{FB_GRAPH_URL}/oauth/access_token",
                params={
                    "client_id": settings.FB_APP_ID,
                    "redirect_uri": redirect_uri,
                    "client_secret": settings.FB_APP_SECRET,
                    "code": code,
                }
            )
            data = response.json()
            if "error" in data:
                raise Exception(data["error"]["message"])
            return data.get("access_token")

    @staticmethod
    async def get_user_pages(user_access_token: str) -> list[dict]:
        """Get all pages managed by the user with their page access tokens."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{FB_GRAPH_URL}/me/accounts",
                params={
                    "access_token": user_access_token,
                    "fields": "id,name,access_token,category",
                    "limit": 100
                }
            )
            data = response.json()
            if "error" in data:
                return [{"error": data["error"]["message"]}]
            
            pages = []
            for item in data.get("data", []):
                pages.append({
                    "page_id": item["id"],
                    "page_name": item["name"],
                    "access_token": item["access_token"],
                    "category": item.get("category", "")
                })
            return pages

    @staticmethod
    async def get_page_detailed_stats(page_id: str, access_token: str) -> dict:
        """Fetch detailed insights for a page (fans, engagement, etc.)"""
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Get basic info & fans
            info_resp = await client.get(
                f"{FB_GRAPH_URL}/{page_id}",
                params={
                    "access_token": access_token,
                    "fields": "name,fan_count,followers_count,engagement,link"
                }
            )
            info = info_resp.json()
            if "error" in info:
                logger.error(f"FB Graph Error on {page_id} info: {info['error']}")
                return {"error": info["error"]["message"]}

            # 2. Get recent posts metrics (Last 10 posts)
            posts_resp = await client.get(
                f"{FB_GRAPH_URL}/{page_id}/posts",
                params={
                    "access_token": access_token,
                    "fields": "id,message,created_time,reactions.summary(true),comments.summary(true),shares",
                    "limit": 10
                }
            )
            posts_json = posts_resp.json()
            if "error" in posts_json:
                logger.error(f"FB Graph Error on {page_id} posts: {posts_json['error']}")
                return {"error": posts_json["error"]["message"]}
                
            posts_data = posts_json.get("data", [])
            
            total_reactions = 0
            total_comments = 0
            total_shares = 0
            
            for post in posts_data:
                total_reactions += post.get("reactions", {}).get("summary", {}).get("total_count", 0)
                total_comments += post.get("comments", {}).get("summary", {}).get("total_count", 0)
                total_shares += post.get("shares", {}).get("count", 0)

            return {
                "id": page_id,
                "name": info.get("name"),
                "fan_count": info.get("fan_count", 0),
                "followers_count": info.get("followers_count", 0),
                "total_engagement": total_reactions + total_comments + total_shares,
                "avg_engagement": round((total_reactions + total_comments + total_shares) / max(len(posts_data), 1), 1),
                "reactions": total_reactions,
                "comments": total_comments,
                "shares": total_shares,
                "post_count": len(posts_data)
            }

    @staticmethod
    async def scrape_fb_reels(profile_url: str, access_token: str, limit: int = 30) -> list[dict]:
        """
        Scrape Facebook Reels/videos from a profile or page.
        Uses Graph API to get video list with metadata.
        Supports:
          - https://www.facebook.com/profile.php?id=XXXX
          - https://www.facebook.com/profile.php?id=XXXX&sk=reels_tab
          - https://www.facebook.com/pagename
          - https://www.facebook.com/pagename/reels
        """
        import re

        # Extract profile/page ID from URL
        fb_id = None

        # Pattern 1: profile.php?id=123456
        id_match = re.search(r'profile\.php\?id=(\d+)', profile_url)
        if id_match:
            fb_id = id_match.group(1)

        # Pattern 2: facebook.com/pagename or facebook.com/pagename/reels
        if not fb_id:
            path_match = re.search(r'facebook\.com/([a-zA-Z0-9_.]+)', profile_url)
            if path_match:
                name = path_match.group(1)
                # Skip common non-page paths
                if name not in ('profile.php', 'watch', 'reel', 'stories', 'groups', 'events'):
                    fb_id = name

        if not fb_id:
            return [{"error": "Không thể trích xuất ID từ URL Facebook"}]

        logger.info(f"Scraping FB Reels for: {fb_id} (limit={limit})")

        videos = []
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                # Step 1: Try to get videos via Graph API
                # Use /videos endpoint which includes Reels
                response = await client.get(
                    f"{FB_GRAPH_URL}/{fb_id}/videos",
                    params={
                        "access_token": access_token,
                        "fields": "id,title,description,length,created_time,thumbnails,source,permalink_url,views",
                        "limit": str(limit),
                    }
                )
                data = response.json()

                if "error" in data:
                    error_msg = data["error"].get("message", "Unknown error")
                    logger.error(f"FB Graph API error for {fb_id}: {error_msg}")
                    return [{"error": f"Facebook API: {error_msg}"}]

                for video in data.get("data", []):
                    video_id = video.get("id", "")
                    # Build the direct FB watch URL
                    permalink = video.get("permalink_url", "")
                    if not permalink:
                        permalink = f"https://www.facebook.com/{fb_id}/videos/{video_id}/"

                    # Get best thumbnail
                    thumbnail = ""
                    thumbs = video.get("thumbnails", {}).get("data", [])
                    if thumbs:
                        # Pick the largest thumbnail
                        best = max(thumbs, key=lambda t: t.get("height", 0) * t.get("width", 0))
                        thumbnail = best.get("uri", "")

                    title = video.get("title", "") or video.get("description", "")[:80] or "Facebook Video"
                    duration = video.get("length", 0)
                    views = video.get("views", 0)

                    videos.append({
                        "id": video_id,
                        "title": title,
                        "url": permalink,
                        "duration": str(int(duration)) if duration else "0",
                        "views": str(views) if views else "0",
                        "thumbnail": thumbnail,
                        "source_url": video.get("source", ""),  # Direct MP4 URL if available
                    })

                # Check for pagination
                paging = data.get("paging", {})
                next_url = paging.get("next", "")
                page_count = 1
                max_pages = 5  # Safety limit

                while next_url and len(videos) < limit and page_count < max_pages:
                    page_count += 1
                    resp = await client.get(next_url)
                    page_data = resp.json()

                    if "error" in page_data:
                        break

                    for video in page_data.get("data", []):
                        if len(videos) >= limit:
                            break
                        video_id = video.get("id", "")
                        permalink = video.get("permalink_url", "")
                        if not permalink:
                            permalink = f"https://www.facebook.com/{fb_id}/videos/{video_id}/"

                        thumbnail = ""
                        thumbs = video.get("thumbnails", {}).get("data", [])
                        if thumbs:
                            best = max(thumbs, key=lambda t: t.get("height", 0) * t.get("width", 0))
                            thumbnail = best.get("uri", "")

                        title = video.get("title", "") or video.get("description", "")[:80] or "Facebook Video"
                        duration = video.get("length", 0)
                        views = video.get("views", 0)

                        videos.append({
                            "id": video_id,
                            "title": title,
                            "url": permalink,
                            "duration": str(int(duration)) if duration else "0",
                            "views": str(views) if views else "0",
                            "thumbnail": thumbnail,
                            "source_url": video.get("source", ""),
                        })

                    next_url = page_data.get("paging", {}).get("next", "")

            except Exception as e:
                logger.error(f"FB Reels scrape error: {e}")
                return [{"error": f"Lỗi quét Facebook Reels: {str(e)}"}]

        logger.info(f"FB Reels: Found {len(videos)} videos for {fb_id}")
        return videos
