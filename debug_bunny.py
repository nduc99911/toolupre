import asyncio
from playwright.async_api import async_playwright

async def test():
    xhs_url = "https://www.rednote.com/explore/6a1d004b0000000007012051"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        try:
            print("Going to dlbunny...")
            await page.goto("https://dlbunny.com/vi/xhs", wait_until="networkidle")
            
            # Find the input box
            print("Typing URL...")
            await page.fill("input[type='text'], input[placeholder*='URL']", xhs_url)
            
            # Find the submit button
            print("Clicking submit...")
            await page.click("button[type='submit'], button:has-text('Tải'), button:has-text('Get')")
            
            # Wait for results
            print("Waiting for results...")
            await page.wait_for_selector("img", timeout=15000)
            await page.wait_for_timeout(3000)
            
            imgs = await page.query_selector_all("img")
            urls = []
            for img in imgs:
                src = await img.get_attribute("src")
                if src and "xhscdn.com" in src:
                    urls.append(src)
                    
            print(f"Found {len(urls)} images via dlbunny!")
            for u in urls:
                print(u)
                
        except Exception as e:
            print("Error:", e)
        finally:
            await browser.close()

asyncio.run(test())
