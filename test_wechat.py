import httpx
import re

note_id = "6a1d906d000000000803cc69"
url = f"https://www.xiaohongshu.com/wx_mp_api/sns/v1/detail/feed?note_id={note_id}"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json"
}
try:
    resp = httpx.get(url, headers=headers, timeout=10)
    print("Status:", resp.status_code)
    data = resp.json()
    if data.get("success"):
        print("Success! Title:", data["data"][0]["note_list"][0]["title"])
        images = data["data"][0]["note_list"][0].get("images_list", [])
        print(f"Found {len(images)} images!")
        for img in images[:3]:
            print(img.get("url"))
    else:
        print("API Failed:", data)
except Exception as e:
    print("Error:", e)
