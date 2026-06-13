import asyncio
import re
import json
import logging
from typing import Dict, List, Optional
from playwright.async_api import async_playwright

logger = logging.getLogger("reupmaster.douyin_scraper")

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}

def extract_sec_uid(url: str) -> Optional[str]:
    match = re.search(r'douyin\.com/user/([^?/&]+)', url)
    return match.group(1) if match else None

def extract_video_from_aweme(item: dict) -> dict:
    video_url = None
    video = item.get("video", {})
    
    if video:
        bit_rate = video.get("bit_rate", [])
        if bit_rate:
            sorted_bit_rate = sorted(bit_rate, key=lambda x: x.get("bit_rate", 0), reverse=True)
            best = sorted_bit_rate[0]
            play_addr = best.get("play_addr", {})
            if play_addr.get("url_list"):
                video_url = play_addr["url_list"][0]
                
        if not video_url:
            play_addr = video.get("play_addr", {})
            if play_addr.get("url_list"):
                video_url = play_addr["url_list"][0]

    author = item.get("author", {}) or item.get("authorInfo", {})
    stats = item.get("statistics", {}) or item.get("stats", {})
    
    return {
        "id": item.get("aweme_id") or item.get("awemeId") or "",
        "desc": item.get("desc", ""),
        "author": author.get("nickname", ""),
        "statistics": {
            "likes": stats.get("digg_count") or stats.get("diggCount", 0),
            "comments": stats.get("comment_count") or stats.get("commentCount", 0),
            "shares": stats.get("share_count") or stats.get("shareCount", 0),
        },
        "videoUrl": video_url,
        "createTime": item.get("create_time") or item.get("createTime", 0)
    }

async def fetch_douyin_profile_videos(profile_url: str, max_count: int = 10) -> Dict:
    sec_uid = extract_sec_uid(profile_url)
    if not sec_uid:
        raise Exception("Không tìm thấy sec_uid trong link. Vui lòng dùng link dạng douyin.com/user/...")
        
    videos = []
    user_info = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=BROWSER_HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 720}
        )
        page = await context.new_page()

        async def handle_response(response):
            if '/aweme/v1/web/aweme/post/' in response.url:
                try:
                    data = await response.json()
                    if data and isinstance(data.get("aweme_list"), list):
                        for item in data["aweme_list"]:
                            v = extract_video_from_aweme(item)
                            if v["id"] and v["videoUrl"]:
                                videos.append(v)
                except Exception:
                    pass

        page.on("response", handle_response)
        
        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(4000)
            
            html = await page.content()
            render_match = re.search(r'<script id="RENDER_DATA"[^>]*>([\s\S]*?)</script>', html)
            if render_match:
                try:
                    from urllib.parse import unquote
                    decoded = unquote(render_match.group(1))
                    render_data = json.loads(decoded)
                    for key, section in render_data.items():
                        if isinstance(section, dict) and "user" in section:
                            u = section["user"]
                            user_info = {
                                "nickname": u.get("nickname") or u.get("uniqueId") or "Unknown",
                                "followerCount": u.get("followerCount") or u.get("mplatform_followers_count", 0),
                            }
                        if isinstance(section, dict) and "post" in section:
                            post_data = section["post"].get("data", [])
                            if isinstance(post_data, list):
                                for item in post_data:
                                    v = extract_video_from_aweme(item)
                                    if v["id"] and v["videoUrl"]:
                                        videos.append(v)
                except Exception as e:
                    logger.error(f"Douyin parsing RENDER_DATA error: {e}")

            # Scroll loop
            scroll_count = 0
            seen_ids = set()
            
            def deduplicate(arr):
                res = []
                for v in arr:
                    if v["id"] not in seen_ids:
                        seen_ids.add(v["id"])
                        res.append(v)
                return res

            unique_videos = deduplicate(videos)
            
            while len(unique_videos) < max_count and scroll_count < 15:
                prev_len = len(unique_videos)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2500)
                
                unique_videos.extend(deduplicate(videos))
                if len(unique_videos) == prev_len:
                    scroll_count += 1
                else:
                    scroll_count = 0
                    
            unique_videos = unique_videos[:max_count]

            if not user_info:
                title = await page.title()
                m = re.search(r'(.*?)(?:的个人主页|的抖音)', title)
                user_info = {"nickname": m.group(1).strip() if m else "Unknown"}
                
            return {
                "userInfo": user_info,
                "videos": unique_videos,
                "totalFound": len(unique_videos)
            }
            
        except Exception as e:
            raise Exception(f"Lỗi khi quét Douyin Profile: {e}")
        finally:
            await context.close()
            await browser.close()

def extract_video_id(url: str) -> Optional[str]:
    video_match = re.search(r'douyin\.com/video/(\d+)', url)
    if video_match: return video_match.group(1)
    note_match = re.search(r'douyin\.com/note/(\d+)', url)
    if note_match: return note_match.group(1)
    return None

async def resolve_short_url(short_url: str) -> str:
    import httpx
    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.head(short_url, headers=BROWSER_HEADERS)
        return str(resp.url)

async def fetch_douyin_video_info(video_url: str) -> dict:
    full_url = video_url
    if 'v.douyin.com' in video_url or 'vt.tiktok.com' in video_url:
        full_url = await resolve_short_url(video_url)
        
    video_id = extract_video_id(full_url)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=BROWSER_HEADERS["User-Agent"],
            viewport={"width": 1280, "height": 720}
        )
        try:
            page = await context.new_page()
            await page.goto(full_url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)
            
            html = await page.content()
            video_data = None
            
            render_match = re.search(r'<script id="RENDER_DATA"[^>]*>([\s\S]*?)</script>', html)
            if render_match:
                from urllib.parse import unquote
                decoded = unquote(render_match.group(1))
                render_data = json.loads(decoded)
                
                for key, section in render_data.items():
                    if isinstance(section, dict) and "aweme" in section:
                        aweme = section["aweme"]
                        detail = aweme.get("detail", aweme)
                        video_data = extract_video_from_aweme(detail)
                        break
            
            if not video_data or not video_data.get("videoUrl"):
                raise Exception("Không thể trích xuất thông tin video hoặc không tìm thấy videoUrl.")
                
            return video_data
        finally:
            await context.close()
            await browser.close()

async def download_douyin_video_file(video_url: str, output_file: str) -> bool:
    import httpx
    headers = {
        'User-Agent': BROWSER_HEADERS['User-Agent'],
        'Referer': 'https://www.douyin.com/',
    }
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        async with client.stream('GET', video_url, headers=headers) as resp:
            if resp.status_code != 200:
                raise Exception(f"Failed to fetch video: {resp.status_code}")
            with open(output_file, 'wb') as f:
                async for chunk in resp.aiter_bytes():
                    f.write(chunk)
    return True
