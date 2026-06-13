import httpx
import re

try:
    resp = httpx.get('https://dlpanda.com/xhs?url=https://www.xiaohongshu.com/explore/6a1d004b0000000007012051', timeout=15.0)
    print('Status:', resp.status_code)
    urls = set(re.findall(r'https?://[^\"\']*xhscdn\.com/[^\"\']+', resp.text))
    print('Found URLs:', len(urls))
    for u in list(urls)[:5]:
        print(u)
except Exception as e:
    print(e)
