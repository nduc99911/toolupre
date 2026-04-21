import os
import sqlite3
import asyncio
import aiosqlite
from pathlib import Path
import sys

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings

async def sync_storage():
    print("🚀 Bắt đầu quét thư mục storage để khôi phục dữ liệu...")
    
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    if os.name == 'nt' and db_path.startswith('/'):
        db_path = db_path[1:]
        
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        
        # 1. Quét thư mục downloads
        download_dir = Path(settings.DOWNLOAD_DIR)
        if not download_dir.exists():
            print(f"❌ Không tìm thấy thư mục: {download_dir}")
            return

        files = list(download_dir.glob("*"))
        restored_count = 0
        
        for file_path in files:
            if file_path.is_dir():
                # Xử lý slideshow
                video_id = file_path.name.split('_')[0]
                # Kiểm tra xem đã có trong DB chưa
                async with db.execute("SELECT id FROM videos WHERE id = ?", (video_id,)) as cursor:
                    if await cursor.fetchone():
                        continue
                
                print(f"📦 Tìm thấy slideshow: {video_id}")
                await db.execute(
                    "INSERT INTO videos (id, source_url, source_platform, title, status, original_path) VALUES (?, ?, ?, ?, ?, ?)",
                    (video_id, "restored_url", "unknown", f"Restored Slideshow {video_id}", "downloaded", str(file_path))
                )
                restored_count += 1
            
            elif file_path.suffix.lower() in ['.mp4', '.mkv', '.webm']:
                # Xử lý video file
                video_id = file_path.name.split('_')[0]
                if len(video_id) < 4: continue # Bỏ qua các file linh tinh
                
                async with db.execute("SELECT id FROM videos WHERE id = ?", (video_id,)) as cursor:
                    if await cursor.fetchone():
                        continue
                
                print(f"🎥 Tìm thấy video: {video_id}")
                await db.execute(
                    "INSERT INTO videos (id, source_url, source_platform, title, status, original_path) VALUES (?, ?, ?, ?, ?, ?)",
                    (video_id, "restored_url", "unknown", f"Restored Video {video_id}", "downloaded", str(file_path))
                )
                restored_count += 1
                
        # 2. Xử lý thư mục processed (nếu có)
        processed_dir = Path(settings.PROCESSED_DIR)
        if processed_dir.exists():
            processed_files = list(processed_dir.glob("processed_*"))
            for p_file in processed_files:
                # filename format: processed_vidid_suffix.mp4
                parts = p_file.name.split('_')
                if len(parts) >= 2:
                    video_id = parts[1]
                    print(f"⚙️ Cập nhật trạng thái đã xử lý cho video: {video_id}")
                    await db.execute(
                        "UPDATE videos SET status = 'processed', processed_path = ? WHERE id = ?",
                        (str(p_file), video_id)
                    )

        await db.commit()
        print(f"✅ Thành công! Đã khôi phục {restored_count} video vào thư viện.")

if __name__ == "__main__":
    asyncio.run(sync_storage())
