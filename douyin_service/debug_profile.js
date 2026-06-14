const { chromium } = require('playwright');

async function test() {
  const url = 'https://www.douyin.com/user/MS4wLjABAAAAjcQdE5qtuNIEEk3LDMn2nPWRcQqfN9WlapA2MouG69T5j6sB7LfFIwYDUbsKyhM-';
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    viewport: { width: 1280, height: 720 }
  });
  const page = await context.newPage();
  
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(4000);
  
  const title = await page.title();
  console.log("Page Title:", title);
  
  // Try extracting from the title
  const titleMatch = title.match(/(.*?) 的个人主页/);
  if (titleMatch) {
     console.log("Extracted Nickname from Title:", titleMatch[1].trim());
  }
  
  // Inspect meta tags
  const description = await page.$eval('meta[name="description"]', el => el.content).catch(() => null);
  console.log("Meta description:", description);

  await browser.close();
}

test().catch(console.error);
