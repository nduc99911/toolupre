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
async def api_list_videos(status: str = None, limit: int = 100):
    """List all videos."""
    videos = await db.get_all_videos(status=status, limit=limit)
    return {"videos": videos, "count": len(videos)}


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

    # Update status to processing immediately so the frontend polling works correctly
    await db.update_video(video_id, {"status": "processing"})

    # Process in background
    import asyncio
    asyncio.create_task(_process_task(video_id, options))

    return {
        "id": video_id,
        "status": "processing",
        "message": "Video processing started"
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


@app.post("/api/process/batch")
async def api_batch_process(request: Request):
    """Process multiple videos."""
    data = await request.json()
    video_ids = data.get("video_ids", [])
    options = data.get("options", VideoProcessor.get_default_options())

    import asyncio
    for vid_id in video_ids:
        # Update immediately to avoid UI freezing or instant-completion bugs on frontend polling
        await db.update_video(vid_id, {"status": "processing"})
        asyncio.create_task(_process_task(vid_id, options))

    return {
        "count": len(video_ids),
        "status": "processing",
        "message": f"Processing {len(video_ids)} videos"
    }


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
    """Remove a Facebook page."""
    await db.delete_fb_page(page_db_id)
    return {"success": True}


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

    # Build full caption
    full_caption = caption
    if hashtags:
        full_caption = f"{caption}\n\n{hashtags}"

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

    # Create scheduled post
    result = await post_scheduler.add_scheduled_post(
        video_id=video_id,
        page_id=page_db_id,
        scheduled_time=scheduled_time,
        caption=caption,
        hashtags=hashtags,
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
