import urllib.request
import re

url = 'https://dlpanda.com/xhs?url=https://www.xiaohongshu.com/explore/6a1d906d000000000803cc69?xsec_token=ABfFNtZFUnINkH1yeML8dUHzh3Fx-TcQ9DhLWHgPqZmtY='
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
try:
    html = urllib.request.urlopen(req, timeout=15).read().decode('utf-8')
    urls = re.findall(r'https?://[^\"\'\s]*xhscdn\.com/[^\"\'\s]+', html)
    print('Found images:', len(set(urls)))
    for u in list(set(urls))[:3]: print(u)
except Exception as e:
    print('Error:', e)
