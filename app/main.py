"""
ReupMaster Pro - Main FastAPI Application
Central hub combining all routers, services, and the web interface.
"""
import os
import uuid
import json
import logging
import mimetypes
from pathlib import Path
from datetime import datetime
from collections import deque

from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.config import settings, BASE_DIR
from app import database as db
from app.services.downloader import download_video, batch_download, detect_platform, get_video_info
from app.services.video_processor import VideoProcessor
from app.services.ai_service import rewrite_text, generate_caption, generate_hashtags
from app.services.facebook_api import FacebookAPI
from app.services.scheduler import post_scheduler
from app.services.process_queue import process_queue


# ─── In-Memory Log Handler ───
class MemoryLogHandler(logging.Handler):
    """Keep last N log lines in memory for the web UI."""
    def __init__(self, capacity=300):
        super().__init__()
        self.buffer = deque(maxlen=capacity)

    def emit(self, record):
        try:
            msg = self.format(record)
            self.buffer.append(msg)
        except Exception:
            pass

    def get_logs(self, count=100):
        return list(self.buffer)[-count:]

    def clear(self):
        self.buffer.clear()


# ─── Logging Setup ───
log_format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)

memory_handler = MemoryLogHandler(capacity=300)
memory_handler.setFormatter(logging.Formatter(log_format))
logging.getLogger().addHandler(memory_handler)  # Root logger

logger = logging.getLogger("reupmaster")

from app.services.progress import video_progress

# ─── FastAPI App ───
app = FastAPI(
    title="ReupMaster Pro",
    description="Social Media Reup & Scheduling Automation Tool",
    version="2.0.0",
)

# ─── Static Files & Templates ───
static_dir = os.path.join(BASE_DIR, "static")
templates_dir = os.path.join(BASE_DIR, "templates")
os.makedirs(static_dir, exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve storage files (thumbnails, videos)
storage_dir = os.path.join(BASE_DIR, "storage")
os.makedirs(storage_dir, exist_ok=True)
app.mount("/storage", StaticFiles(directory=storage_dir), name="storage")

templates = Jinja2Templates(directory=templates_dir)


# ─── Startup / Shutdown Events ───
@app.on_event("startup")
async def startup():
    await db.init_db()
    post_scheduler.start()
    logger.info("ReupMaster Pro started!")


@app.on_event("shutdown")
async def shutdown():
    post_scheduler.stop()
    logger.info("ReupMaster Pro stopped.")


# ═══════════════════════════════════════════
# WEB INTERFACE
# ═══════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main web interface."""
    return templates.TemplateResponse("index.html", {"request": request})


# ═══════════════════════════════════════════
# API: DASHBOARD / STATS
# ═══════════════════════════════════════════

@app.get("/api/stats")
async def api_stats():
    """Get dashboard statistics."""
    stats = await db.get_stats()
    scheduler_status = post_scheduler.get_status()
    return {
        **stats,
        "scheduler": scheduler_status,
    }


# ═══════════════════════════════════════════
# API: DOWNLOAD
# ═══════════════════════════════════════════

@app.post("/api/download")
async def api_download(request: Request):
    """Download a single video."""
    data = await request.json()
    url = data.get("url", "").strip()

    if not url:
        raise HTTPException(400, "URL is required")

    video_id = str(uuid.uuid4())[:8]
    platform = detect_platform(url)

    # Create initial record
    await db.create_video({
        "id": video_id,
        "source_url": url,
        "source_platform": platform,
        "status": "pending",
    })

    # Download in background
    import asyncio
    asyncio.create_task(_download_task(url, video_id))

    return {
        "id": video_id,
        "status": "downloading",
        "platform": platform,
        "message": f"Download started for {platform} video"
    }


async def _download_task(url: str, video_id: str):
    """Background download task."""
    try:
        result = await download_video(url, video_id)
        if "error" in result:
            logger.error(f"Download failed for {video_id}: {result['error']}")
        else:
            logger.info(f"Download completed for {video_id}")
    except Exception as e:
        logger.error(f"Download exception for {video_id}: {e}")
        await db.update_video(video_id, {
            "status": "failed",
            "error_message": str(e)
        })


@app.post("/api/download/batch")
async def api_batch_download(request: Request):
    """Download multiple videos."""
    data = await request.json()
    urls = data.get("urls", [])

    if isinstance(urls, str):
        urls = [u.strip() for u in urls.split("\n") if u.strip()]

    if not urls:
        raise HTTPException(400, "URLs are required")

    results = []
    for url in urls:
        video_id = str(uuid.uuid4())[:8]
        platform = detect_platform(url)
        await db.create_video({
            "id": video_id,
            "source_url": url,
            "source_platform": platform,
            "status": "pending",
        })
        import asyncio
        asyncio.create_task(_download_task(url, video_id))
        results.append({
            "id": video_id,
            "url": url,
            "platform": platform,
            "status": "downloading"
        })

    return {"count": len(results), "videos": results}


@app.post("/api/video/info")
async def api_video_info(request: Request):
    """Get video info without downloading."""
    data = await request.json()
    url = data.get("url", "").strip()
    if not url:
        raise HTTPException(400, "URL is required")

    info = await get_video_info(url)
    return info


# ═══════════════════════════════════════════
# API: VIDEO LIBRARY
# ═══════════════════════════════════════════

@app.get("/api/videos")
async def api_list_videos(status: str = None, folder_id: str = None, limit: int = 200):
    """List all videos with status and folder filter."""
    videos = await db.get_all_videos(status=status, folder_id=folder_id, limit=limit)
    return {"videos": videos, "count": len(videos)}


@app.post("/api/videos/batch-delete")
async def api_batch_delete_videos(request: Request):
    """Delete multiple videos at once."""
    params = await request.json()
    video_ids = params.get("video_ids", [])
    
    if not video_ids:
        raise HTTPException(400, "No video IDs provided")
        
    deleted_count = 0
    for vid_id in video_ids:
        # We reuse the logic from delete_video
        video = await db.get_video(vid_id)
        if not video: continue
        
        # Physical cleanup
        for path in [video.get("original_path"), video.get("processed_path"), video.get("thumbnail_path")]:
            if path and os.path.exists(path):
                try:
                    if os.path.isdir(path):
                        import shutil
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                except Exception as e:
                    print(f"Cleanup error for {path}: {e}")
        
        # DB deletion
        await db.delete_video(vid_id)
        deleted_count += 1
        
    return {"success": True, "message": f"Đã xóa {deleted_count} video thành công"}

@app.post("/api/videos/batch-move")
async def api_batch_move_videos(request: Request):
    """Move multiple videos to a folder."""
    params = await request.json()
    video_ids = params.get("video_ids", [])
    folder_id = params.get("folder_id") # Can be uuid or None
    
    if not video_ids:
        raise HTTPException(400, "No video IDs provided")
        
    count = await db.move_videos_to_folder(video_ids, folder_id)
    return {"success": True, "message": f"Đã chuyển {count} video vào thư mục thành công"}

# ─── Folders API ───

@app.get("/api/folders")
async def api_get_folders():
    folders = await db.get_all_folders()
    return {"folders": folders}

@app.post("/api/folders")
async def api_create_folder(request: Request):
    import uuid
    params = await request.json()
    name = params.get("name")
    if not name:
        raise HTTPException(400, "Folder name is required")
        
    folder_id = str(uuid.uuid4())[:8]
    folder = await db.create_folder(folder_id, name)
    return folder

@app.delete("/api/folders/{folder_id}")
async def api_delete_folder(folder_id: str):
    await db.delete_folder(folder_id)
    return {"success": True}


@app.get("/api/videos/{video_id}")
async def api_get_video(video_id: str):
    """Get single video details."""
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    return video


@app.delete("/api/videos/{video_id}")
async def api_delete_video(video_id: str):
    """Delete a video and its files."""
    video = await db.get_video(video_id)
    if video:
        # Delete files
        for path_key in ["original_path", "processed_path", "thumbnail_path"]:
            path = video.get(path_key)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        await db.delete_video(video_id)
    return {"success": True}


@app.get("/api/videos/{video_id}/status")
async def api_video_status(video_id: str):
    """Get video download/processing status with progress."""
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    
    from app.services.progress import video_progress
    return {
        "id": video_id,
        "status": video["status"],
        "error_message": video.get("error_message", ""),
        "progress": video_progress.get(video_id, 0),
    }


# ═══════════════════════════════════════════
# API: VIDEO PROCESSING
# ═══════════════════════════════════════════

@app.get("/api/process/options")
async def api_process_options():
    """Get available processing options."""
    return {
        "options": VideoProcessor.AVAILABLE_OPTIONS,
        "defaults": VideoProcessor.get_default_options(),
    }


@app.post("/api/process/batch")
async def api_batch_process(request: Request):
    """Process multiple videos."""
    data = await request.json()
    video_ids = data.get("video_ids", [])
    options = data.get("options", VideoProcessor.get_default_options())

    # Add all to sequential queue
    await process_queue.add_videos(video_ids, options)

    return {
        "count": len(video_ids),
        "status": "processing",
        "message": f"Processing {len(video_ids)} videos"
    }


@app.post("/api/process/{video_id}")
async def api_process_video(video_id: str, request: Request):
    """Process a video with given options."""
    data = await request.json()
    options = data.get("options", VideoProcessor.get_default_options())

    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    if video["status"] not in ("downloaded", "processed", "failed"):
        raise HTTPException(400, f"Video status is '{video['status']}', cannot process")

    # Add to sequential queue
    await process_queue.add_videos([video_id], options)
    
    return {
        "id": video_id,
        "status": "processing",
        "message": "Video added to sequential processing queue"
    }


async def _process_task(video_id: str, options: dict):
    """Background processing task."""
    try:
        result = await VideoProcessor.process_video(video_id, options)
        if "error" in result:
            logger.error(f"Processing failed for {video_id}: {result['error']}")
        else:
            logger.info(f"Processing completed for {video_id}")
    except Exception as e:
        logger.error(f"Processing exception for {video_id}: {e}")
        await db.update_video(video_id, {
            "status": "failed",
            "error_message": str(e)
        })


@app.get("/api/process/queue")
async def api_get_process_queue():
    """Get sequential processing queue status."""
    return process_queue.get_status()


# ═══════════════════════════════════════════
# API: AI TEXT SERVICES
# ═══════════════════════════════════════════

@app.post("/api/ai/rewrite")
async def api_ai_rewrite(request: Request):
    """Rewrite text using AI."""
    data = await request.json()
    text = data.get("text", "")
    style = data.get("style", "viral")
    language = data.get("language", "vi")

    if not text:
        raise HTTPException(400, "Text is required")

    result = await rewrite_text(text, style, language)
    return result


@app.post("/api/ai/caption")
async def api_ai_caption(request: Request):
    """Generate a caption for a video."""
    data = await request.json()
    title = data.get("title", "")
    description = data.get("description", "")
    style = data.get("style", "viral")
    language = data.get("language", "vi")
    niche = data.get("niche", "")

    result = await generate_caption(title, description, style, language, niche)
    return result


@app.post("/api/ai/hashtags")
async def api_ai_hashtags(request: Request):
    """Generate hashtags for a topic."""
    data = await request.json()
    topic = data.get("topic", "")
    count = data.get("count", 10)
    language = data.get("language", "vi")

    if not topic:
        raise HTTPException(400, "Topic is required")

    hashtags = await generate_hashtags(topic, count, language)
    return {"hashtags": hashtags}


@app.post("/api/ai/video-caption/{video_id}")
async def api_ai_video_caption(video_id: str, request: Request):
    """Generate caption for a specific video and save to DB."""
    data = await request.json()
    style = data.get("style", "viral")
    language = data.get("language", "vi")
    niche = data.get("niche", "")

    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    result = await generate_caption(
        video.get("title", ""),
        video.get("description", ""),
        style, language, niche
    )

    if "error" not in result:
        # Save to database
        await db.update_video(video_id, {
            "ai_title": result.get("caption", "")[:200],
            "ai_description": json.dumps(result, ensure_ascii=False),
        })

    return result


# ═══════════════════════════════════════════
# API: FACEBOOK PAGES
# ═══════════════════════════════════════════

@app.get("/api/fb/pages")
async def api_list_fb_pages():
    """List all configured Facebook pages."""
    pages = await db.get_all_fb_pages()
    return {"pages": pages}


@app.post("/api/fb/pages")
async def api_add_fb_page(request: Request):
    """Add a Facebook page with access token."""
    data = await request.json()
    access_token = data.get("access_token", "").strip()

    if not access_token:
        raise HTTPException(400, "Access token is required")

    # Attempt to extend token if it's a user token or short-lived
    access_token = await FacebookAPI.extend_token(access_token)

    # Verify token
    page_info = await FacebookAPI.verify_token(access_token)
    if "error" in page_info:
        raise HTTPException(400, f"Token verification failed: {page_info['error']}")

    # Save to DB
    page_data = {
        "id": str(uuid.uuid4())[:8],
        "page_id": page_info["page_id"],
        "page_name": page_info["page_name"],
        "access_token": access_token,
        "category": page_info.get("category", ""),
        "is_active": 1,
    }
    await db.create_fb_page(page_data)

    return {
        "success": True,
        "page": page_data,
        "message": f"Page '{page_info['page_name']}' added successfully"
    }


@app.post("/api/fb/pages/from-user-token")
async def api_import_pages_from_user(request: Request):
    """Import all pages from a user access token."""
    data = await request.json()
    user_token = data.get("user_token", "").strip()

    if not user_token:
        raise HTTPException(400, "User access token is required")

    # Step 1: Extend the user token to 60 days
    user_token = await FacebookAPI.extend_token(user_token)

    # Step 2: Fetch pages (the page tokens returned will now be permanent/long-lived)
    pages = await FacebookAPI.get_user_pages(user_token)
    if pages and "error" in pages[0]:
        raise HTTPException(400, pages[0]["error"])

    saved = []
    for page in pages:
        page_data = {
            "id": str(uuid.uuid4())[:8],
            "page_id": page["page_id"],
            "page_name": page["page_name"],
            "access_token": page["access_token"],
            "category": page.get("category", ""),
            "is_active": 1,
        }
        await db.create_fb_page(page_data)
        saved.append(page_data)

    return {
        "success": True,
        "count": len(saved),
        "pages": saved,
    }


@app.delete("/api/fb/pages/{page_db_id}")
async def api_delete_fb_page(page_db_id: str):
    await db.delete_fb_page(page_db_id)
    return {"success": True}

@app.post("/api/fb/pages/{page_db_id}/debug")
async def api_debug_fb_token(page_db_id: str):
    """Get info about a page token."""
    pages = await db.get_all_fb_pages()
    page = next((p for p in pages if p["id"] == page_db_id), None)
    if not page:
        raise HTTPException(404, "Page not found")
        
    info = await FacebookAPI.get_token_info(page["access_token"])
    return info


@app.put("/api/fb/pages/{page_db_id}")
async def api_update_fb_page(page_db_id: str, request: Request):
    """Update a Facebook page's token."""
    data = await request.json()
    access_token = data.get("access_token", "").strip()

    if not access_token:
        raise HTTPException(400, "Access token is required")

    page_info = await FacebookAPI.verify_token(access_token)
    if "error" in page_info:
        raise HTTPException(400, f"Token verification failed: {page_info['error']}")

    pages = await db.get_all_fb_pages()
    page = next((p for p in pages if p["id"] == page_db_id), None)
    if not page:
        raise HTTPException(404, "Page not found")

    if page_info["page_id"] != page["page_id"]:
        raise HTTPException(400, "Token does not match the original Page ID")

    # Save to DB
    page_data = {
        "id": page_db_id,
        "page_id": page_info["page_id"],
        "page_name": page_info["page_name"],
        "access_token": access_token,
        "category": page_info.get("category", page.get("category", "")),
        "is_active": 1,
    }
    await db.create_fb_page(page_data)

    return {
        "success": True,
        "page": page_data,
        "message": f"Token updated for '{page_info['page_name']}'"
    }


@app.get("/api/fb/analytics")
async def api_fb_analytics():
    """Fetch real-time stats for all active pages and save to history."""
    pages = await db.get_all_fb_pages()
    
    if not pages:
        return {"pages": [], "count": 0}

    async def fetch_and_save(page):
        try:
            stats = await FacebookAPI.get_page_detailed_stats(page["page_id"], page["access_token"])
            if "error" not in stats:
                await db.save_page_stats({
                    "page_db_id": page["id"],
                    "fan_count": stats.get("fan_count", 0),
                    "followers_count": stats.get("followers_count", 0),
                    "total_engagement": stats.get("total_engagement", 0),
                    "avg_engagement": stats.get("avg_engagement", 0),
                    "post_count_recent": stats.get("post_count", 0)
                })
                stats["page_db_id"] = page["id"]
                return stats
            return None
        except Exception as e:
            logger.error(f"Failed to fetch stats for page {page['page_name']}: {e}")
            return None

    import asyncio
    tasks = [fetch_and_save(p) for p in pages]
    task_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    results = [res for res in task_results if isinstance(res, dict)]
            
    return {"pages": results, "count": len(results)}


@app.get("/api/fb/pages/{page_db_id}/history")
async def api_fb_page_history(page_db_id: str, days: int = 30):
    """Get historical stats for a specific page."""
    history = await db.get_page_stats_history(page_db_id, days)
    return {"history": history}


# ═══════════════════════════════════════════
# API: FACEBOOK OAUTH LOGIN
# ═══════════════════════════════════════════

@app.get("/api/fb/login-url")
async def api_fb_login_url(request: Request):
    """Generate Facebook OAuth login URL for the frontend."""
    if not settings.FB_APP_ID or not settings.FB_APP_SECRET:
        raise HTTPException(400, "FB_APP_ID and FB_APP_SECRET must be set in .env")

    # Build callback URL dynamically based on the current request
    callback_url = str(request.base_url).rstrip("/") + "/api/fb/callback"

    # Permissions needed for page management + video posting
    scopes = "pages_show_list,pages_read_engagement,pages_manage_posts,publish_video"

    oauth_url = (
        f"https://www.facebook.com/v21.0/dialog/oauth"
        f"?client_id={settings.FB_APP_ID}"
        f"&redirect_uri={callback_url}"
        f"&scope={scopes}"
        f"&response_type=code"
    )

    return {"url": oauth_url, "callback_url": callback_url}


@app.get("/api/fb/callback")
async def api_fb_callback(request: Request, code: str = None, error: str = None):
    """
    Facebook OAuth callback.
    Exchanges code for user token, gets long-lived token, fetches pages, saves them.
    Returns an HTML page that auto-closes and notifies the parent window.
    """
    if error:
        return HTMLResponse(f"""
        <html><body><script>
            window.opener && window.opener.postMessage({{
                type: 'fb_auth_error',
                error: '{error}'
            }}, '*');
            window.close();
        </script><p>Error: {error}. This window will close automatically.</p></body></html>
        """)

    if not code:
        return HTMLResponse("""
        <html><body><script>
            window.opener && window.opener.postMessage({
                type: 'fb_auth_error',
                error: 'No authorization code received'
            }, '*');
            window.close();
        </script><p>No code received. This window will close.</p></body></html>
        """)

    callback_url = str(request.base_url).rstrip("/") + "/api/fb/callback"

    try:
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Exchange code for short-lived user token
            token_resp = await client.get(
                "https://graph.facebook.com/v21.0/oauth/access_token",
                params={
                    "client_id": settings.FB_APP_ID,
                    "client_secret": settings.FB_APP_SECRET,
                    "redirect_uri": callback_url,
                    "code": code,
                }
            )
            token_data = token_resp.json()

            if "error" in token_data:
                err_msg = token_data["error"].get("message", "Unknown error")
                logger.error(f"FB OAuth token exchange failed: {err_msg}")
                return HTMLResponse(f"""
                <html><body><script>
                    window.opener && window.opener.postMessage({{
                        type: 'fb_auth_error',
                        error: '{err_msg}'
                    }}, '*');
                    window.close();
                </script><p>Token error: {err_msg}</p></body></html>
                """)

            short_token = token_data.get("access_token", "")

            # Step 2: Exchange for long-lived token (60 days)
            long_resp = await client.get(
                "https://graph.facebook.com/v21.0/oauth/access_token",
                params={
                    "grant_type": "fb_exchange_token",
                    "client_id": settings.FB_APP_ID,
                    "client_secret": settings.FB_APP_SECRET,
                    "fb_exchange_token": short_token,
                }
            )
            long_data = long_resp.json()
            user_token = long_data.get("access_token", short_token)

            # Step 3: Get user info
            me_resp = await client.get(
                "https://graph.facebook.com/v21.0/me",
                params={"access_token": user_token, "fields": "id,name"}
            )
            me_data = me_resp.json()
            user_name = me_data.get("name", "Unknown")

            # Step 4: Get all pages managed by the user
            pages_resp = await client.get(
                "https://graph.facebook.com/v21.0/me/accounts",
                params={
                    "access_token": user_token,
                    "fields": "id,name,access_token,category,fan_count",
                    "limit": 100,
                }
            )
            pages_data = pages_resp.json()

            if "error" in pages_data:
                err_msg = pages_data["error"].get("message", "Unknown error")
                logger.error(f"FB pages fetch failed: {err_msg}")
                return HTMLResponse(f"""
                <html><body><script>
                    window.opener && window.opener.postMessage({{
                        type: 'fb_auth_error',
                        error: '{err_msg}'
                    }}, '*');
                    window.close();
                </script><p>Pages error: {err_msg}</p></body></html>
                """)

            # Step 5: Save all pages to database
            saved_pages = []
            for page in pages_data.get("data", []):
                page_data = {
                    "id": str(uuid.uuid4())[:8],
                    "page_id": page["id"],
                    "page_name": page.get("name", ""),
                    "access_token": page.get("access_token", ""),
                    "category": page.get("category", ""),
                    "is_active": 1,
                }
                await db.create_fb_page(page_data)
                saved_pages.append({
                    "id": page_data["id"],
                    "name": page.get("name", ""),
                    "category": page.get("category", ""),
                })

            logger.info(f"FB OAuth success: user={user_name}, {len(saved_pages)} pages imported")

            import json as _json
            pages_json = _json.dumps(saved_pages)

            return HTMLResponse(f"""
            <html>
            <head><title>Facebook Login Success</title>
            <style>
                body {{
                    font-family: 'Inter', sans-serif;
                    background: #0a0a0f;
                    color: #e8e8f0;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    min-height: 100vh;
                    text-align: center;
                }}
                .card {{
                    background: rgba(26,26,40,0.9);
                    padding: 40px;
                    border-radius: 16px;
                    border: 1px solid rgba(255,255,255,0.06);
                    max-width: 400px;
                }}
                .icon {{ font-size: 48px; margin-bottom: 16px; }}
                h2 {{ margin-bottom: 8px; }}
                p {{ color: #8888a8; font-size: 14px; }}
                .count {{ color: #00b894; font-weight: 700; font-size: 24px; }}
            </style>
            </head>
            <body>
            <div class="card">
                <div class="icon">✅</div>
                <h2>Đăng nhập thành công!</h2>
                <p>Xin chào <strong>{user_name}</strong></p>
                <p class="count">{len(saved_pages)} Pages</p>
                <p>đã được import. Cửa sổ sẽ tự đóng...</p>
            </div>
            <script>
                window.opener && window.opener.postMessage({{
                    type: 'fb_auth_success',
                    user: '{user_name}',
                    pages: {pages_json},
                    count: {len(saved_pages)}
                }}, '*');
                setTimeout(() => window.close(), 2500);
            </script>
            </body></html>
            """)

    except Exception as e:
        logger.error(f"FB OAuth callback error: {e}")
        return HTMLResponse(f"""
        <html><body><script>
            window.opener && window.opener.postMessage({{
                type: 'fb_auth_error',
                error: '{str(e)}'
            }}, '*');
            window.close();
        </script><p>Error: {str(e)}</p></body></html>
        """)


# ═══════════════════════════════════════════
# API: PUBLISH
# ═══════════════════════════════════════════

@app.post("/api/publish")
async def api_publish_video(request: Request):
    """Publish a video to a Facebook page immediately."""
    data = await request.json()
    video_id = data.get("video_id", "")
    page_db_id = data.get("page_id", "")
    caption = data.get("caption", "")
    hashtags = data.get("hashtags", "")

    # Get video
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    # Get page
    pages = await db.get_all_fb_pages()
    page = next((p for p in pages if p["id"] == page_db_id), None)
    if not page:
        raise HTTPException(404, "Facebook page not found")

    video_path = video.get("processed_path") or video.get("original_path")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(400, "Video file not found")

    # Build full caption (fallback to original title if empty)
    final_caption = caption if caption.strip() else video.get("title", "")
    final_hashtags = hashtags if hashtags.strip() else ""
    
    full_caption = final_caption
    if final_hashtags:
        full_caption = f"{final_caption}\n\n{final_hashtags}"

    # Publish
    result = await FacebookAPI.post_video(
        page_id=page["page_id"],
        access_token=page["access_token"],
        video_path=video_path,
        caption=full_caption,
        title=video.get("ai_title") or video.get("title", ""),
    )

    if result.get("success"):
        await db.update_video(video_id, {"status": "published"})

    return result


# ═══════════════════════════════════════════
# API: SCHEDULED POSTS
# ═══════════════════════════════════════════

@app.post("/api/schedule")
async def api_schedule_post(request: Request):
    """Schedule a video post for later."""
    data = await request.json()
    video_id = data.get("video_id", "")
    page_db_id = data.get("page_id", "")
    scheduled_time = data.get("scheduled_time", "")
    caption = data.get("caption", "")
    hashtags = data.get("hashtags", "")

    if not all([video_id, page_db_id, scheduled_time]):
        raise HTTPException(400, "video_id, page_id, and scheduled_time are required")

    # Validate video exists
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    # Fallback to original title if empty
    final_caption = caption if caption.strip() else video.get("title", "")
    final_hashtags = hashtags if hashtags.strip() else ""

    # Create scheduled post
    result = await post_scheduler.add_scheduled_post(
        video_id=video_id,
        page_id=page_db_id,
        scheduled_time=scheduled_time,
        caption=final_caption,
        hashtags=final_hashtags,
    )

    return {
        "success": True,
        "post": result,
        "message": f"Post scheduled for {scheduled_time}"
    }


@app.get("/api/schedule")
async def api_list_scheduled(status: str = None):
    """List scheduled posts."""
    posts = await db.get_all_scheduled_posts(status)
    return {"posts": posts, "count": len(posts)}


@app.post("/api/schedule/retry-failed")
async def api_retry_failed_posts():
    """Reset failed scheduled posts to pending."""
    adb = await db.get_db()
    try:
        # Update all 'failed' posts to 'pending'
        await adb.execute(
            "UPDATE scheduled_posts SET status = 'pending', error_message = '' WHERE status = 'failed'"
        )
        await adb.commit()
        return {"success": True, "message": "Đã đặt lại các bài lỗi về trạng thái chờ đăng"}
    finally:
        await adb.close()


@app.delete("/api/schedule/{post_id}")
async def api_cancel_scheduled(post_id: str):
    """Cancel a scheduled post."""
    await post_scheduler.cancel_post(post_id)
    return {"success": True}


@app.get("/api/scheduler/status")
async def api_scheduler_status():
    """Get scheduler status."""
    return post_scheduler.get_status()


# ═══════════════════════════════════════════
# API: SETTINGS
# ═══════════════════════════════════════════

@app.get("/api/settings")
async def api_get_settings():
    """Get app settings (safe, no secrets)."""
    return {
        "ai_provider": settings.AI_PROVIDER,
        "openai_model": settings.OPENAI_MODEL,
        "gemini_model": settings.GEMINI_MODEL,
        "has_openai_key": bool(settings.OPENAI_API_KEY and settings.OPENAI_API_KEY != "sk-your-openai-key-here"),
        "has_gemini_key": bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != "your-gemini-key-here"),
        "has_fb_app": bool(settings.FB_APP_ID and settings.FB_APP_ID != "your-fb-app-id"),
        "ffmpeg_path": settings.FFMPEG_PATH or "system PATH",
        "download_dir": settings.DOWNLOAD_DIR,
        "processed_dir": settings.PROCESSED_DIR,
        "auto_cleanup": settings.AUTO_CLEANUP_VIDEO
    }


# ═══════════════════════════════════════════
# SERVE VIDEO FILES
# ═══════════════════════════════════════════

@app.get("/api/file/{video_id}/{file_type}")
async def api_serve_file(video_id: str, file_type: str):
    """Serve a video or thumbnail file with correct MIME type."""
    video = await db.get_video(video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    if file_type == "original":
        path = video.get("original_path", "")
    elif file_type == "processed":
        path = video.get("processed_path", "")
    elif file_type == "thumbnail":
        path = video.get("thumbnail_path", "")
    else:
        raise HTTPException(400, "Invalid file type")

    if not path or not os.path.exists(path):
        raise HTTPException(404, "File not found")

    # Determine correct media type
    media_type = None
    ext = os.path.splitext(path)[1].lower()
    type_map = {
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.mkv': 'video/x-matroska',
        '.avi': 'video/x-msvideo',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp',
    }
    media_type = type_map.get(ext, mimetypes.guess_type(path)[0])

    return FileResponse(path, media_type=media_type)


# ═══════════════════════════════════════════
# API: LOGS
# ═══════════════════════════════════════════

@app.get("/api/logs")
async def api_get_logs(count: int = 100):
    """Get recent application logs."""
    logs = memory_handler.get_logs(count)
    return {"logs": logs, "count": len(logs)}


@app.delete("/api/logs")
async def api_clear_logs():
    """Clear log buffer."""
    memory_handler.clear()
    return {"success": True}


# ═══════════════════════════════════════════
# API: MASS SCHEDULING (SO9 Style)
# ═══════════════════════════════════════════

@app.post("/api/mass-schedule")
async def api_mass_schedule(request: Request):
    """
    Mass schedule: distribute multiple videos across multiple pages
    with staggered timing (SO9-style mass posting).
    """
    data = await request.json()
    video_ids = data.get("video_ids", [])
    page_ids = data.get("page_ids", [])
    start_time = data.get("start_time", "")       # ISO datetime string
    interval_minutes = int(data.get("interval", 30))  # minutes between posts
    caption = data.get("caption", "")
    hashtags = data.get("hashtags", "")
    use_ai_spin = data.get("use_ai_spin", False)

    if not video_ids or not page_ids or not start_time:
        raise HTTPException(400, "video_ids, page_ids, and start_time are required")

    from datetime import datetime, timedelta

    try:
        base_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    except ValueError:
        base_time = datetime.fromisoformat(start_time)

    all_pages = await db.get_all_fb_pages()
    page_map = {p["id"]: p for p in all_pages}

    created_posts = []
    slot_index = 0

    for vid_id in video_ids:
        video = await db.get_video(vid_id)
        if not video:
            continue

        for pg_id in page_ids:
            page = page_map.get(pg_id)
            if not page:
                continue

            # Calculate staggered time
            scheduled_time = base_time + timedelta(minutes=slot_index * interval_minutes)

            # Fallback to original title if empty
            final_caption = caption if caption.strip() else video.get("title", "")
            final_hashtags = hashtags if hashtags.strip() else ""

            # AI Content Spinning: generate unique caption per page
            post_caption = final_caption
            post_hashtags = final_hashtags
            if use_ai_spin and final_caption:
                try:
                    spin_result = await _spin_caption_for_page(
                        caption, page.get("page_name", ""),
                        video.get("title", ""), video.get("description", "")
                    )
                    if "caption" in spin_result:
                        post_caption = spin_result["caption"]
                    if "hashtags" in spin_result and spin_result["hashtags"]:
                        post_hashtags = " ".join(spin_result["hashtags"])
                except Exception as e:
                    logger.warning(f"AI spin failed for {pg_id}: {e}")

            result = await post_scheduler.add_scheduled_post(
                video_id=vid_id,
                page_id=pg_id,
                scheduled_time=scheduled_time.isoformat(),
                caption=post_caption,
                hashtags=post_hashtags,
            )
            created_posts.append({
                "video_id": vid_id,
                "page_id": pg_id,
                "page_name": page.get("page_name", ""),
                "scheduled_time": scheduled_time.isoformat(),
                "post_id": result.get("id", ""),
            })
            slot_index += 1

    logger.info(f"Mass schedule: created {len(created_posts)} posts from {len(video_ids)} videos x {len(page_ids)} pages")

    return {
        "success": True,
        "count": len(created_posts),
        "posts": created_posts,
        "message": f"Đã tạo {len(created_posts)} bài đăng lên lịch!"
    }


async def _spin_caption_for_page(base_caption: str, page_name: str,
                                  video_title: str, video_desc: str) -> dict:
    """Use AI to spin/personalize a caption for a specific page."""
    prompt = f"""Bạn là chuyên gia content marketing trên Facebook.
Viết lại caption dưới đây để tạo một phiên bản HOÀN TOÀN KHÁC về mặt từ ngữ nhưng GIỮ NGUYÊN ý nghĩa.
Mục tiêu: tránh bị Facebook phát hiện là nội dung spam/trùng lặp khi đăng lên nhiều Page.

Caption gốc: {base_caption}
Tên Page: {page_name}
Tiêu đề video: {video_title}

Yêu cầu:
1. Paraphrase 100% - KHÔNG giữ nguyên bất kỳ câu nào từ gốc
2. Thêm emoji hợp lý
3. Có thể mention tên Page "{page_name}" một cách tự nhiên
4. Tạo 5-8 hashtag mới liên quan
5. Giọng văn tự nhiên, cuốn hút

Trả về JSON:
{{"caption": "...", "hashtags": ["#tag1", "#tag2", ...]}}"""

    try:
        provider = settings.AI_PROVIDER.lower()
        import asyncio as _asyncio

        if provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            resp = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": "You are a content spinning expert. Always respond in valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.95,
                max_tokens=800,
            )
            result_text = resp.choices[0].message.content
        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel(settings.GEMINI_MODEL)
            resp = await _asyncio.to_thread(model.generate_content, prompt)
            result_text = resp.text
        else:
            return {"caption": base_caption}

        # Parse JSON from response
        import re
        json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
        return {"caption": result_text}
    except Exception as e:
        logger.warning(f"Spin caption error: {e}")
        return {"caption": base_caption}


# ═══════════════════════════════════════════
# API: BULK PROFILE DOWNLOAD (SO9 9Downloader)
# ═══════════════════════════════════════════

@app.post("/api/profile/list-videos")
async def api_list_profile_videos(request: Request):
    """
    List all videos from a user profile URL (TikTok, Douyin, YouTube).
    Uses yt-dlp --flat-playlist to enumerate without downloading.
    """
    data = await request.json()
    profile_url = data.get("url", "").strip()
    limit = int(data.get("limit", 30))

    if not profile_url:
        raise HTTPException(400, "Profile URL is required")

    import subprocess
    from concurrent.futures import ThreadPoolExecutor

    def _list_videos():
        cmd = [
            "yt-dlp",
            "--flat-playlist",
            "--playlist-end", str(limit),
            "--print", "%(id)s|||%(title)s|||%(url)s|||%(duration)s|||%(view_count)s|||%(thumbnail)s",
            "--no-warnings",
            "--no-check-certificates",
            profile_url,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, encoding='utf-8', errors='replace')
            videos = []
            for line in result.stdout.strip().split("\n"):
                if "|||" not in line:
                    continue
                parts = line.split("|||")
                if len(parts) >= 3:
                    videos.append({
                        "id": parts[0] if parts[0] != "NA" else "",
                        "title": parts[1] if len(parts) > 1 and parts[1] != "NA" else "Untitled",
                        "url": parts[2] if len(parts) > 2 and parts[2] != "NA" else "",
                        "duration": parts[3] if len(parts) > 3 and parts[3] != "NA" else "0",
                        "views": parts[4] if len(parts) > 4 and parts[4] != "NA" else "0",
                        "thumbnail": parts[5] if len(parts) > 5 and parts[5] != "NA" else "",
                    })
            return videos
        except Exception as e:
            return [{"error": str(e)}]

    import asyncio
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    videos = await loop.run_in_executor(executor, _list_videos)

    if videos and "error" in videos[0]:
        raise HTTPException(500, videos[0]["error"])

    logger.info(f"Profile scan: found {len(videos)} videos from {profile_url}")
    return {"videos": videos, "count": len(videos), "profile_url": profile_url}


@app.post("/api/profile/download-selected")
async def api_download_selected(request: Request):
    """Download selected videos from a profile listing."""
    data = await request.json()
    urls = data.get("urls", [])

    if not urls:
        raise HTTPException(400, "No URLs provided")

    results = []
    import asyncio
    for url in urls:
        video_id = str(uuid.uuid4())[:8]
        platform = detect_platform(url)
        await db.create_video({
            "id": video_id,
            "source_url": url,
            "source_platform": platform,
            "status": "pending",
        })
        asyncio.create_task(_download_task(url, video_id))
        results.append({"id": video_id, "url": url, "platform": platform, "status": "downloading"})

    return {"count": len(results), "videos": results}


# ═══════════════════════════════════════════
# API: DASHBOARD ANALYTICS (SO9 Style)
# ═══════════════════════════════════════════

@app.get("/api/dashboard/analytics")
async def api_dashboard_analytics():
    """Get enhanced analytics for dashboard charts."""
    analytics = await db.get_dashboard_analytics()
    return analytics


# ═══════════════════════════════════════════
# API: AFFILIATE AUTOMATION
# ═══════════════════════════════════════════

@app.get("/api/affiliate/platforms")
async def api_affiliate_platforms():
    """List supported affiliate platforms."""
    from app.services.affiliate_service import get_affiliate_platforms
    return {"platforms": get_affiliate_platforms()}


@app.post("/api/affiliate/generate-caption")
async def api_affiliate_caption(request: Request):
    """Generate AI-powered affiliate caption with product link."""
    data = await request.json()
    
    from app.services.affiliate_service import generate_affiliate_caption
    
    result = await generate_affiliate_caption(
        video_title=data.get("video_title", ""),
        video_description=data.get("video_description", ""),
        product_keywords=data.get("product_keywords", ""),
        affiliate_link=data.get("affiliate_link", ""),
        style=data.get("style", "soft_sell"),
        language=data.get("language", "vi"),
    )

    if "error" in result:
        raise HTTPException(500, result["error"])

    return result


# ═══════════════════════════════════════════
# API: AUTO SEEDING (Like/Comment/Share)
# ═══════════════════════════════════════════

@app.get("/api/seeding/accounts")
async def api_seeding_accounts():
    """List all seeding accounts."""
    adb = await db.get_db()
    try:
        cursor = await adb.execute("SELECT * FROM seeding_accounts ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        accounts = []
        for r in rows:
            d = dict(r)
            d.pop("access_token", None)  # Don't expose token to frontend
            accounts.append(d)
        return {"accounts": accounts}
    finally:
        await adb.close()


@app.post("/api/seeding/accounts")
async def api_add_seeding_account(request: Request):
    """Add a new seeding account (clone/via)."""
    data = await request.json()
    token = data.get("access_token", "").strip()
    name = data.get("name", "").strip()
    account_type = data.get("account_type", "clone")
    daily_limit = int(data.get("daily_limit", 50))

    if not token:
        raise HTTPException(400, "Access token is required")

    # Verify token by getting user info
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://graph.facebook.com/v19.0/me",
                params={"access_token": token, "fields": "id,name"}
            )
            user_data = resp.json()
            if "error" in user_data:
                raise HTTPException(400, f"Token không hợp lệ: {user_data['error']['message']}")
            
            fb_user_id = user_data.get("id", "")
            if not name:
                name = user_data.get("name", f"Via-{fb_user_id[:6]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Lỗi xác thực token: {str(e)}")

    import uuid
    account_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()

    adb = await db.get_db()
    try:
        await adb.execute("""
            INSERT INTO seeding_accounts (id, name, fb_user_id, access_token, account_type, daily_limit, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (account_id, name, fb_user_id, token, account_type, daily_limit, now))
        await adb.commit()
        return {"message": f"Đã thêm tài khoản: {name}", "id": account_id, "name": name, "fb_user_id": fb_user_id}
    finally:
        await adb.close()


@app.delete("/api/seeding/accounts/{account_id}")
async def api_delete_seeding_account(account_id: str):
    """Delete a seeding account."""
    adb = await db.get_db()
    try:
        await adb.execute("DELETE FROM seeding_accounts WHERE id = ?", (account_id,))
        await adb.execute("DELETE FROM seeding_tasks WHERE account_id = ?", (account_id,))
        await adb.commit()
        return {"message": "Đã xóa tài khoản"}
    finally:
        await adb.close()


@app.post("/api/seeding/create-plan")
async def api_create_seeding_plan(request: Request):
    """Create a seeding plan for a published post."""
    data = await request.json()
    fb_post_id = data.get("fb_post_id", "").strip()
    page_name = data.get("page_name", "")
    actions = data.get("actions", {"like": True, "comment": True, "share": False})
    delay_min = int(data.get("delay_min", 30))
    delay_max = int(data.get("delay_max", 180))
    custom_comments = data.get("custom_comments", [])

    if not fb_post_id:
        raise HTTPException(400, "fb_post_id is required")

    # Get active seeding accounts
    adb = await db.get_db()
    try:
        cursor = await adb.execute(
            "SELECT * FROM seeding_accounts WHERE status = 'active'"
        )
        accounts = [dict(r) for r in await cursor.fetchall()]

        if not accounts:
            raise HTTPException(400, "Chưa có tài khoản seeding nào. Hãy thêm Via/Clone trước.")

        # Create plan
        from app.services.seeding_service import create_seeding_plan
        tasks = await create_seeding_plan(
            fb_post_id=fb_post_id,
            page_name=page_name,
            accounts=accounts,
            actions=actions,
            delay_range=(delay_min, delay_max),
        )

        # Override comments if custom ones provided
        if custom_comments:
            comment_tasks = [t for t in tasks if t["action_type"] == "comment"]
            for i, task in enumerate(comment_tasks):
                task["comment_text"] = custom_comments[i % len(custom_comments)]

        # Save tasks to DB
        for task in tasks:
            await adb.execute("""
                INSERT INTO seeding_tasks (id, fb_post_id, page_name, account_id, action_type, comment_text, status, scheduled_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (task["id"], task["fb_post_id"], task["page_name"], task["account_id"],
                  task["action_type"], task["comment_text"], task["status"], task["scheduled_at"], task["created_at"]))
        
        await adb.commit()

        return {
            "message": f"Đã tạo {len(tasks)} tác vụ seeding cho bài {fb_post_id}",
            "total_tasks": len(tasks),
            "tasks": [{
                "id": t["id"],
                "action": t["action_type"],
                "account": t.get("account_name", t["account_id"]),
                "scheduled": t["scheduled_at"],
                "comment": t.get("comment_text", "")[:30],
            } for t in tasks],
        }
    finally:
        await adb.close()


@app.get("/api/seeding/tasks")
async def api_seeding_tasks(limit: int = 50):
    """Get recent seeding tasks."""
    adb = await db.get_db()
    try:
        cursor = await adb.execute("""
            SELECT st.*, sa.name as account_name
            FROM seeding_tasks st
            LEFT JOIN seeding_accounts sa ON st.account_id = sa.id
            ORDER BY st.created_at DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        return {"tasks": [dict(r) for r in rows]}
    finally:
        await adb.close()


@app.get("/api/seeding/stats")
async def api_seeding_stats():
    """Get seeding statistics."""
    adb = await db.get_db()
    try:
        stats = {}
        
        # Account count
        cursor = await adb.execute("SELECT COUNT(*) as cnt FROM seeding_accounts WHERE status = 'active'")
        row = await cursor.fetchone()
        stats["active_accounts"] = dict(row)["cnt"]
        
        # Task stats
        cursor = await adb.execute("""
            SELECT status, COUNT(*) as cnt FROM seeding_tasks GROUP BY status
        """)
        rows = await cursor.fetchall()
        stats["tasks_by_status"] = {dict(r)["status"]: dict(r)["cnt"] for r in rows}
        
        # Today's actions
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cursor = await adb.execute("""
            SELECT COUNT(*) as cnt FROM seeding_tasks 
            WHERE status = 'completed' AND executed_at LIKE ?
        """, (f"{today}%",))
        row = await cursor.fetchone()
        stats["actions_today"] = dict(row)["cnt"]
        
        # Total completed
        cursor = await adb.execute("SELECT COUNT(*) as cnt FROM seeding_tasks WHERE status = 'completed'")
        row = await cursor.fetchone()
        stats["total_completed"] = dict(row)["cnt"]
        
        # Pending
        cursor = await adb.execute("SELECT COUNT(*) as cnt FROM seeding_tasks WHERE status = 'pending'")
        row = await cursor.fetchone()
        stats["total_pending"] = dict(row)["cnt"]
        
        return stats
    finally:
        await adb.close()


@app.get("/api/seeding/comments")
async def api_seeding_comment_templates():
    """Get available comment templates."""
    from app.services.seeding_service import SEEDING_COMMENTS
    return {"comments": SEEDING_COMMENTS}


@app.post("/api/seeding/reset-daily")
async def api_reset_daily_limits():
    """Reset daily action counters for all seeding accounts."""
    adb = await db.get_db()
    try:
        await adb.execute("UPDATE seeding_accounts SET actions_today = 0")
        await adb.commit()
        return {"message": "Đã reset giới hạn hàng ngày cho tất cả tài khoản"}
    finally:
        await adb.close()
