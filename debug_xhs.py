import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

async def test():
    url = "https://www.xiaohongshu.com/explore/6a1d004b0000000007012051"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        stealth = Stealth()
        await stealth.apply_stealth_async(page)
        print("Visiting...")
        resp = await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(4000)
        
        print("URL after navigation:", page.url)
        content = await page.content()
        print("Content length:", len(content))
        
        if "404" in page.url or "404" in content:
            print("Redirected to 404 or blocked!")
        
        state_str = await page.evaluate("() => { try { return JSON.stringify(window.__INITIAL_STATE__); } catch(e) { return null; } }")
        if state_str:
            print("Found __INITIAL_STATE__!")
            import re
            urls = re.findall(r'https?://[^"]*xhscdn\.com/[^"]+', state_str)
            print("Found image URLs:", len(urls))
            for u in urls[:5]:
                print(u.replace('\\u002F', '/'))
        else:
            print("__INITIAL_STATE__ not found.")
            
        await browser.close()

asyncio.run(test())
