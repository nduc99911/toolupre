from fastapi import APIRouter, Request, HTTPException
import uuid
import asyncio
from typing import List, Dict

from app.services.douyin_service import fetch_video_info, fetch_profile_videos, download_douyin_video_task
from app import database as db
from app.services.downloader import download_video, detect_platform

router = APIRouter(prefix="/api/profile", tags=["Profile"])

@router.post("/list-videos")
async def profile_list_videos(request: Request):
    """Scan Profile and get videos (currently supports Douyin and partially others via fallback)."""
    data = await request.json()
    url = data.get("url", "").strip()
    limit = data.get("limit", 30)
    
    if not url:
        raise HTTPException(400, "Vui lòng nhập link profile")
        
    platform = detect_platform(url)
    
    try:
        max_count = min(max(int(limit), 1), 100)
        if platform == "douyin":
            # Use our new Playwright Douyin scraper
            profile_data = await fetch_profile_videos(url, max_count)
            videos = []
            for v in profile_data["videos"]:
                videos.append({
                    "url": f"https://www.douyin.com/video/{v['id']}",
                    "title": v.get("desc", ""),
                    "thumbnail": v.get("cover", ""),
                    "duration": v.get("duration", 0),
                    "views": v.get("statistics", {}).get("plays", 0),
                    "id": v["id"]
                })
            return {"success": True, "videos": videos, "user_info": profile_data["userInfo"]}
        else:
            # Not supported natively here yet
            raise HTTPException(400, f"Chức năng quét profile chưa hỗ trợ đầy đủ cho nền tảng {platform}. Vui lòng dùng link Douyin.")
            
    except Exception as e:
        raise HTTPException(500, str(e))

@router.post("/download-selected")
async def profile_download_selected(request: Request):
    """Start downloading selected videos from profile scan."""
    data = await request.json()
    urls = data.get("urls", [])
    
    if not urls:
        raise HTTPException(400, "No URLs provided")
        
    count = 0
    for url in urls:
        if not url: continue
        video_id = str(uuid.uuid4())[:8]
        platform = detect_platform(url)
        
        # Create initial record
        await db.create_video({
            "id": video_id,
            "source_url": url,
            "source_platform": platform,
            "status": "pending",
        })
        
        if platform == "douyin":
            asyncio.create_task(download_douyin_video_task(url, video_id))
        else:
            # Fallback for others
            asyncio.create_task(download_video(url, video_id))
        count += 1
        
    return {
        "success": True,
        "count": count,
        "message": f"Started downloading {count} videos"
    }

# Also keep the specific Douyin api we made earlier just in case
douyin_api_router = APIRouter(prefix="/api/douyin", tags=["Douyin"])

@douyin_api_router.post("/parse")
async def douyin_parse(request: Request):
    """Parse Douyin video info using Playwright."""
    data = await request.json()
    url = data.get("url", "").strip()
    
    if not url:
        raise HTTPException(400, "Vui lòng nhập link video Douyin")
        
    try:
        info = await fetch_video_info(url)
        return {"success": True, "data": info}
    except Exception as e:
        raise HTTPException(500, str(e))

@douyin_api_router.post("/download")
async def douyin_download(request: Request):
    data = await request.json()
    url = data.get("url", "").strip()
    if not url:
        raise HTTPException(400, "URL is required")
        
    video_id = str(uuid.uuid4())[:8]
    await db.create_video({
        "id": video_id,
        "source_url": url,
        "source_platform": "douyin",
        "status": "pending",
    })
    asyncio.create_task(download_douyin_video_task(url, video_id))
    
    return {"id": video_id, "status": "downloading", "platform": "douyin"}
