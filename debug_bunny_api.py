import asyncio
from playwright.async_api import async_playwright

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        async def handle_request(route):
            print(f"Request: {route.request.method} {route.request.url}")
            await route.continue_()

        async def handle_response(response):
            if "api" in response.url or "parse" in response.url or "video" in response.url:
                print(f"Response: {response.url} - {response.status}")
                if response.status == 200:
                    try:
                        print("Body:", await response.text())
                    except:
                        pass
                        
        page.route("**/*", handle_request)
        page.on("response", handle_response)
        
        await page.goto("https://dlbunny.com/vi/xhs", wait_until="networkidle")
        await page.fill("input", "https://www.rednote.com/explore/6a1d004b0000000007012051")
        
        # Click the button (might be type submit or class btn)
        buttons = await page.query_selector_all("button")
        for b in buttons:
            text = await b.inner_text()
            if "Tải" in text or "Download" in text or "Get" in text or "Phân tích" in text:
                print("Clicking:", text)
                await b.click()
                break
                
        await page.wait_for_timeout(10000)
        await browser.close()

asyncio.run(test())
