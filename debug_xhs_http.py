import httpx
import re

url = "https://www.xiaohongshu.com/explore/6a1d906d000000000803cc69?xsec_token=ABfFNtZFUnINkH1yeML8dUHzh3Fx-TcQ9DhLWHgPqZmtY=&xsec_source=pc_feed"
headers = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

resp = httpx.get(url, headers=headers, follow_redirects=True)
print("Status:", resp.status_code)
print("URL:", resp.url)
state = re.search(r'window\.__INITIAL_STATE__=({.*?})</script>', resp.text)
if state:
    print("Found INITIAL_STATE")
    import json
    urls = re.findall(r'https?://[^"]*xhscdn\.com/[^"]+', state.group(1))
    print(f"Found {len(urls)} images")
else:
    print("Not found")
    print(resp.text[:500])
