import httpx
import re

url = "https://www.xiaohongshu.com/explore/6a1d906d000000000803cc69?xsec_token=ABfFNtZFUnINkH1yeML8dUHzh3Fx-TcQ9DhLWHgPqZmtY=&xsec_source=pc_feed"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9"
}

resp = httpx.get(url, headers=headers, follow_redirects=True)
print("Status:", resp.status_code)
print("URL:", resp.url)
state = re.search(r'window\.__INITIAL_STATE__=({.*?})</script>', resp.text)
if state:
    print("Found INITIAL_STATE!")
else:
    print("Not found.")
