import os
import re
import json
import logging
import urllib.parse
from playwright.async_api import async_playwright
import httpx
import uuid
import aiofiles

from app.config import settings
from app import database as db
from app.services.progress import video_progress

logger = logging.getLogger("reupmaster.douyin_service")

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Sec-Ch-Ua': '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}

def extract_video_id(url: str) -> str:
    match = re.search(r'douyin\.com/video/(\d+)', url)
    if match: return match.group(1)
    match = re.search(r'douyin\.com/note/(\d+)', url)
    if match: return match.group(1)
    return None

def extract_sec_uid(url: str) -> str:
    match = re.search(r'douyin\.com/user/([^?/&]+)', url)
    if match: return match.group(1)
    return None

def extract_video_from_aweme(item: dict) -> dict:
    video_url = None
    video = item.get("video")
    if video:
        bit_rate = video.get("bit_rate", [])
        if bit_rate:
            sorted_br = sorted(bit_rate, key=lambda x: x.get("bit_rate", 0), reverse=True)
            best = sorted_br[0]
            play_addr = best.get("play_addr", {})
            if play_addr.get("url_list"):
                video_url = play_addr["url_list"][0]
        if not video_url:
            play_addr = video.get("play_addr", {})
            if play_addr.get("url_list"):
                video_url = play_addr["url_list"][0]
                
    author = item.get("author") or item.get("authorInfo") or {}
    stats = item.get("statistics") or item.get("stats") or {}
    
    return {
        "id": item.get("aweme_id") or item.get("awemeId") or "",
        "desc": item.get("desc", ""),
        "author": author.get("nickname", ""),
        "authorAvatar": (author.get("avatar_thumb") or author.get("avatarThumb") or {}).get("url_list", [""])[0],
        "statistics": {
            "likes": stats.get("digg_count") or stats.get("diggCount") or 0,
            "comments": stats.get("comment_count") or stats.get("commentCount") or 0,
            "shares": stats.get("share_count") or stats.get("shareCount") or 0,
            "plays": stats.get("play_count") or stats.get("playCount") or 0,
        },
        "cover": (video.get("cover") or video.get("origin_cover") or {}).get("url_list", [""])[0] if video else "",
        "duration": video.get("duration", 0) if video else 0,
        "videoUrl": video_url,
        "musicTitle": item.get("music", {}).get("title", ""),
        "musicAuthor": item.get("music", {}).get("author", ""),
        "createTime": item.get("create_time") or item.get("createTime") or 0,
    }

async def resolve_short_url(short_url: str) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True, headers=BROWSER_HEADERS) as client:
            resp = await client.get(short_url)
            return str(resp.url)
    except Exception as e:
        raise Exception(f"Cannot resolve short link: {e}")

async def fetch_video_info(video_url: str) -> dict:
    full_url = video_url
    if 'v.douyin.com' in video_url or 'vt.tiktok.com' in video_url:
        full_url = await resolve_short_url(video_url)
    
    video_id = extract_video_id(full_url)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=BROWSER_HEADERS['User-Agent'],
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()
        try:
            await page.goto(full_url, wait_until='domcontentloaded', timeout=15000)
        except:
            pass
        await page.wait_for_timeout(3000)
        html = await page.content()
        await browser.close()
        
    video_data = None
    render_match = re.search(r'<script id="RENDER_DATA"[^>]*>([\s\S]*?)<\/script>', html)
    if render_match:
        try:
            decoded = urllib.parse.unquote(render_match.group(1))
            render_data = json.loads(decoded)
            for key, section in render_data.items():
                if isinstance(section, dict) and section.get("aweme"):
                    aweme = section["aweme"]
                    detail = aweme.get("detail") or aweme
                    
                    video_data = {
                        "id": detail.get("awemeId") or detail.get("aweme_id") or video_id,
                        "desc": detail.get("desc", ""),
                        "author": (detail.get("authorInfo") or detail.get("author", {})).get("nickname", "Unknown"),
                        "authorAvatar": ((detail.get("authorInfo") or {}).get("avatarThumb") or (detail.get("author") or {}).get("avatar_thumb") or {}).get("url_list", [""])[0],
                        "statistics": {
                            "likes": (detail.get("stats") or detail.get("statistics") or {}).get("diggCount", 0) or (detail.get("stats") or detail.get("statistics") or {}).get("digg_count", 0),
                            "comments": (detail.get("stats") or detail.get("statistics") or {}).get("commentCount", 0) or (detail.get("stats") or detail.get("statistics") or {}).get("comment_count", 0),
                            "shares": (detail.get("stats") or detail.get("statistics") or {}).get("shareCount", 0) or (detail.get("stats") or detail.get("statistics") or {}).get("share_count", 0),
                            "plays": (detail.get("stats") or detail.get("statistics") or {}).get("playCount", 0) or (detail.get("stats") or detail.get("statistics") or {}).get("play_count", 0),
                        },
                        "cover": ((detail.get("video") or {}).get("cover") or (detail.get("video") or {}).get("origin_cover") or {}).get("url_list", [""])[0],
                        "duration": (detail.get("video") or {}).get("duration", 0) / 1000.0 if (detail.get("video") or {}).get("duration", 0) > 1000 else (detail.get("video") or {}).get("duration", 0),
                        "videoUrl": None,
                        "musicTitle": (detail.get("music") or {}).get("title", ""),
                        "musicAuthor": (detail.get("music") or {}).get("author", ""),
                    }
                    video = detail.get("video")
                    if video:
                        bit_rate = video.get("bit_rate", [])
                        if bit_rate:
                            sorted_br = sorted(bit_rate, key=lambda x: x.get("bit_rate", 0), reverse=True)
                            best = sorted_br[0]
                            play_addr = best.get("play_addr", {})
                            if play_addr.get("url_list"):
                                video_data["videoUrl"] = play_addr["url_list"][0]
                        if not video_data["videoUrl"]:
                            play_addr = video.get("play_addr", {})
                            if play_addr.get("url_list"):
                                video_data["videoUrl"] = play_addr["url_list"][0]
                    break
        except Exception as e:
            logger.error(f"Error parsing RENDER_DATA: {e}")
            
    if not video_data:
        raise Exception("Không thể trích xuất thông tin video.")
    return video_data

async def fetch_profile_videos(profile_url: str, max_count: int = 10) -> dict:
    full_url = profile_url
    if 'v.douyin.com' in profile_url or 'vt.tiktok.com' in profile_url:
        full_url = await resolve_short_url(profile_url)
        
    sec_uid = extract_sec_uid(full_url)
    if not sec_uid:
        raise Exception("Không thể trích xuất sec_uid từ link profile.")
        
    videos = []
    user_info = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=BROWSER_HEADERS['User-Agent'],
            viewport={'width': 1280, 'height': 720}
        )
        page = await context.new_page()
        
        async def handle_response(response):
            try:
                if '/aweme/v1/web/aweme/post/' in response.url:
                    data = await response.json()
                    if data and data.get("aweme_list") and isinstance(data["aweme_list"], list):
                        for item in data["aweme_list"]:
                            videos.append(extract_video_from_aweme(item))
            except:
                pass
                
        page.on("response", handle_response)
        
        try:
            await page.goto(full_url, wait_until='domcontentloaded', timeout=15000)
        except:
            pass
        await page.wait_for_timeout(4000)
        
        html = await page.content()
        render_match = re.search(r'<script id="RENDER_DATA"[^>]*>([\s\S]*?)<\/script>', html)
        if render_match:
            try:
                decoded = urllib.parse.unquote(render_match.group(1))
                render_data = json.loads(decoded)
                for key, section in render_data.items():
                    if isinstance(section, dict):
                        if section.get("user"):
                            u = section["user"]
                            user_info = {
                                "secUid": u.get("secUid") or u.get("sec_uid") or sec_uid,
                                "uid": u.get("uid") or u.get("uniqueId") or "",
                                "nickname": u.get("nickname") or u.get("uniqueId") or "Unknown",
                                "avatar": (u.get("avatarThumb") or u.get("avatar_thumb") or u.get("avatarMedium") or {}).get("url_list", [""])[0],
                                "signature": u.get("signature") or u.get("desc") or "",
                                "followerCount": u.get("followerCount") or u.get("mplatform_followers_count") or 0,
                                "followingCount": u.get("followingCount") or u.get("following_count") or 0,
                                "totalFavorited": u.get("totalFavorited") or u.get("total_favorited") or 0,
                                "awemeCount": u.get("awemeCount") or u.get("aweme_count") or 0,
                                "verified": u.get("customVerify") or u.get("verification_type") is not None or False,
                            }
                        if section.get("post") and section["post"].get("data") and isinstance(section["post"]["data"], list):
                            for item in section["post"]["data"]:
                                videos.append(extract_video_from_aweme(item))
            except Exception as e:
                logger.error(f"[Profile] Error parsing RENDER_DATA: {e}")
                
        scroll_count = 0
        max_scrolls = 20
        
        def deduplicate(arr):
            seen = set()
            res = []
            for item in arr:
                if not item or not item.get("id") or item["id"] in seen:
                    continue
                seen.add(item["id"])
                res.append(item)
            return res
            
        while len(deduplicate(videos)) < max_count and scroll_count < max_scrolls:
            prev_len = len(videos)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2500)
            if len(videos) == prev_len:
                scroll_count += 1
            else:
                scroll_count = 0
                
        videos = deduplicate(videos)[:max_count]
        
        if not user_info:
            user_info = {
                "secUid": sec_uid, "uid": "", "nickname": "Unknown", "avatar": "", "signature": "",
                "followerCount": 0, "followingCount": 0, "totalFavorited": 0, "awemeCount": 0, "verified": False,
            }
            
        await browser.close()
        
    return {
        "userInfo": user_info,
        "videos": videos,
        "totalFound": len(videos)
    }

async def download_douyin_video_task(url: str, video_id: str):
    """Specific task for downloading douyin video using python logic instead of yt-dlp."""
    try:
        video_progress[video_id] = 10
        video_data = await fetch_video_info(url)
        video_url = video_data.get("videoUrl")
        
        if not video_url:
            raise Exception("No video URL found in Douyin response.")
            
        video_progress[video_id] = 30
        
        output_dir = settings.DOWNLOAD_DIR
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{video_id}_douyin.mp4")
        
        # Download the video
        headers = {
            'User-Agent': BROWSER_HEADERS['User-Agent'],
            'Referer': 'https://www.douyin.com/',
        }
        
        async with httpx.AsyncClient(timeout=60, headers=headers) as client:
            async with client.stream("GET", video_url) as stream_resp:
                if stream_resp.status_code != 200:
                    raise Exception(f"Download failed with status {stream_resp.status_code}")
                
                total_size = int(stream_resp.headers.get("Content-Length", 0))
                downloaded = 0
                
                async with aiofiles.open(output_file, 'wb') as f:
                    async for chunk in stream_resp.aiter_bytes(chunk_size=8192):
                        await f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            # 30% to 90%
                            progress = 30 + (downloaded / total_size) * 60
                            video_progress[video_id] = round(progress, 1)
                            
        file_size = os.path.getsize(output_file)
        video_progress[video_id] = 100
        
        result = {
            "id": video_id,
            "source_url": url,
            "source_platform": "douyin",
            "title": video_data.get("desc", ""),
            "description": video_data.get("desc", ""),
            "original_path": output_file,
            "original_filename": os.path.basename(output_file),
            "thumbnail_path": "", # Can download cover if needed
            "file_size": file_size,
            "duration": video_data.get("duration", 0),
            "width": 1080, # approximate
            "height": 1920, # approximate
            "status": "downloaded",
        }
        
        await db.update_video(video_id, result)
        logger.info(f"[{video_id}] Douyin Playwright Download completed: {output_file}")
        
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        logger.error(f"[{video_id}] Douyin Playwright Error: {err_msg}")
        await db.update_video(video_id, {
            "status": "failed",
            "error_message": str(e) or "Unknown error"
        })
