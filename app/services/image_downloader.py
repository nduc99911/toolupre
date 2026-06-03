import os
import uuid
import json
import logging
import asyncio
from typing import List, Dict

from app.config import settings
from app.services.downloader import get_video_info, detect_platform, _run_command_async

logger = logging.getLogger("reupmaster.image_downloader")

async def download_images_from_url(url: str, save_dir: str = None) -> Dict:
    """
    Download images from a given URL (TikTok Slideshow, Facebook post, RedNote).
    """
    platform = detect_platform(url)
    
    # If it's xiaohongshu/rednote
    if any(domain in url.lower() for domain in ["xiaohongshu.com", "xhslink.com", "rednote.com"]):
        platform = "rednote"
    
    post_id = str(uuid.uuid4())[:8]
    if not save_dir:
        # Create a common folder for downloaded images
        save_dir = os.path.join(settings.DOWNLOAD_DIR, "images", f"{platform}_{post_id}")
    
    os.makedirs(save_dir, exist_ok=True)
    
    result = {
        "id": post_id,
        "platform": platform,
        "url": url,
        "save_dir": save_dir,
        "images": [],
        "error": None
    }
    
    try:
        if platform == "tiktok":
            result["images"] = await _download_tiktok_images(url, save_dir)
        elif platform == "rednote":
            result["images"] = await _download_rednote_images(url, save_dir)
        elif platform == "facebook":
            result["images"] = await _download_facebook_images(url, save_dir)
        else:
            # Fallback to yt-dlp thumbnail extraction
            result["images"] = await _download_tiktok_images(url, save_dir)
            
        if not result["images"]:
            result["error"] = "Không tìm thấy ảnh nào hoặc không hỗ trợ trích xuất ảnh từ link này."
    except Exception as e:
        logger.error(f"Image download error: {e}")
        result["error"] = str(e)
        
    return result

async def _download_tiktok_images(url: str, save_dir: str) -> List[str]:
    """Extract and download images from TikTok slideshow using yt-dlp."""
    import httpx
    info = await get_video_info(url)
    if "error" in info:
        raise Exception(info["error"])
        
    raw_info = info.get("raw_info", {})
    image_urls = []
    
    for thumb in raw_info.get("thumbnails", []):
        thumb_url = thumb.get("url", "")
        if thumb_url and ("image" in thumb.get("id", "") or
                         "slideshow" in thumb_url.lower() or
                         "musically" in thumb_url.lower() or
                         thumb.get("id", "").startswith("postpage_image")):
            image_urls.append(thumb_url)
            
    if not image_urls:
        for thumb in raw_info.get("thumbnails", []):
            thumb_url = thumb.get("url", "")
            if thumb_url and "100x100" not in thumb_url and "avatar" not in thumb_url:
                w = thumb.get("width", 0)
                h = thumb.get("height", 0)
                if w >= 200 or (w == 0 and h == 0):
                    image_urls.append(thumb_url)
                    
    if not image_urls:
        main_thumb = raw_info.get("thumbnail", "")
        if main_thumb:
            image_urls = [main_thumb]
            
    # Remove duplicates
    image_urls = list(set(image_urls))
    
    downloaded_files = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for i, img_url in enumerate(image_urls):
            try:
                resp = await client.get(img_url)
                if resp.status_code == 200:
                    ext = "jpg"
                    content_type = resp.headers.get("content-type", "")
                    if "png" in content_type: ext = "png"
                    elif "webp" in content_type: ext = "webp"
                    
                    img_path = os.path.join(save_dir, f"image_{i+1:03d}.{ext}")
                    with open(img_path, "wb") as f:
                        f.write(resp.content)
                    downloaded_files.append(img_path)
            except Exception as e:
                logger.warning(f"Failed to download TikTok image {i}: {e}")
                
    return downloaded_files

async def _download_rednote_images(url: str, save_dir: str) -> List[str]:
    """
    Extract images from Xiaohongshu/RedNote using HTTPX instead of Playwright.
    Requires xsec_token in the URL to bypass login blocks.
    """
    import httpx
    import re
    import json
    
    downloaded_files = []
    image_urls = []
    
    # If user accidentally pastes a 404 redirected link, extract the noteId and xsec_token
    if "404" in url and "noteId=" in url:
        note_match = re.search(r'noteId=([a-zA-Z0-9]+)', url)
        token_match = re.search(r'xsec_token=([^&]+)', url)
        if note_match:
            note_id = note_match.group(1)
            url = f"https://www.xiaohongshu.com/explore/{note_id}"
            if token_match:
                url += f"?xsec_token={token_match.group(1)}&xsec_source=pc_feed"
            
    # RedNote often blocks desktop access to rednote.com, replacing with xiaohongshu.com is safer
    if "rednote.com" in url:
        url = url.replace("rednote.com", "xiaohongshu.com")
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            
            # Try to extract from window.__INITIAL_STATE__
            state_match = re.search(r'window\.__INITIAL_STATE__=({.*?})</script>', resp.text)
            if state_match:
                state_str = state_match.group(1)
                
                # Find all xhscdn image links
                urls = re.findall(r'https?://[^"\'\s]*xhscdn\.com/[^"\'\s]+', state_str)
                for u in urls:
                    # Clean up escaped unicode if any
                    u = u.replace('\\u002F', '/')
                    if u not in image_urls:
                        image_urls.append(u)
                        
            # Fallback to DOM elements if regex fails
            if not image_urls:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, 'html.parser')
                for img in soup.find_all('meta', attrs={'name': 'og:image'}):
                    image_urls.append(img.get('content'))
                for img in soup.find_all('meta', property='og:image'):
                    image_urls.append(img.get('content'))
                    
            # Remove duplicates & filter
            image_urls = list(set([u for u in image_urls if u]))
            
    except Exception as e:
        logger.warning(f"RedNote HTTP parsing issue: {e}")
            
    # Download the images
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for i, img_url in enumerate(image_urls):
            try:
                # Add headers for XHS
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                resp = await client.get(img_url, headers=headers)
                if resp.status_code == 200:
                    ext = "jpg"
                    img_path = os.path.join(save_dir, f"rednote_{i+1:03d}.{ext}")
                    with open(img_path, "wb") as f:
                        f.write(resp.content)
                    downloaded_files.append(img_path)
            except Exception as e:
                logger.warning(f"Failed to download RedNote image: {e}")

    return downloaded_files

async def _download_facebook_images(url: str, save_dir: str) -> List[str]:
    """
    Extract images from a Facebook post using yt-dlp first (it can sometimes grab thumbnails of posts),
    or fallback to Playwright.
    """
    # First, try to see if yt-dlp can get the thumbnails (useful for single images or video thumbs)
    downloaded_files = await _download_tiktok_images(url, save_dir)
    if downloaded_files:
        return downloaded_files
        
    # If not, use Playwright to scrape
    from playwright.async_api import async_playwright
    import httpx
    
    image_urls = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            # Wait a bit for FB's React to load images
            await page.wait_for_timeout(3000)
            
            # Find high-res image elements on Facebook posts
            imgs = await page.query_selector_all("img")
            for img in imgs:
                src = await img.get_attribute("src")
                if src and ("scontent" in src or "fbcdn" in src):
                    # Filter out tiny icons and profile pics based on URL pattern or width/height
                    w = await img.get_attribute("width")
                    if w and int(w) > 200:
                        image_urls.append(src)
                    elif not w:
                        image_urls.append(src)
        except Exception as e:
            logger.warning(f"Playwright FB parsing issue: {e}")
        finally:
            await browser.close()
            
    # Remove duplicates
    image_urls = list(set(image_urls))
    
    # Download
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for i, img_url in enumerate(image_urls):
            try:
                resp = await client.get(img_url)
                if resp.status_code == 200:
                    ext = "jpg"
                    img_path = os.path.join(save_dir, f"fb_{i+1:03d}.{ext}")
                    with open(img_path, "wb") as f:
                        f.write(resp.content)
                    downloaded_files.append(img_path)
            except Exception as e:
                logger.warning(f"Failed to download FB image: {e}")
                
    return downloaded_files
