import httpx
url = "https://api.kwwv.cn/api/xhs?url=https://www.xiaohongshu.com/explore/6a1d906d000000000803cc69"
try:
    resp = httpx.get(url, timeout=15)
    print("Status:", resp.status_code)
    print("Response:", resp.text)
except Exception as e:
    print("Error:", e)
