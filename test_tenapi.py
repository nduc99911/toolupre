import httpx
url = "https://tenapi.cn/v2/xhs?url=https://www.xiaohongshu.com/explore/6a1d906d000000000803cc69"
try:
    resp = httpx.get(url, timeout=15)
    print("Status:", resp.status_code)
    data = resp.json()
    print("Response:", data)
except Exception as e:
    print("Error:", e)
