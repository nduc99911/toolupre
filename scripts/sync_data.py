import os
import sqlite3
from pathlib import Path
import sys

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings

def sync_storage():
    print("🚀 Bắt đầu quét thư mục storage để khôi phục dữ liệu...")
    
    db_path = settings.DATABASE_URL.replace("sqlite:///", "")
    if os.name == 'nt' and db_path.startswith('/'):
        db_path = db_path[1:]
    
    if not os.path.exists(db_path):
        print(f"❌ Không tìm thấy file database tại: {db_path}")
        return

    # Use standard sqlite3 for simplicity and zero-dependency
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    db = conn.cursor()
    
    try:
        # 1. Quét thư mục downloads
        download_dir = Path(settings.DOWNLOAD_DIR)
        if not download_dir.exists():
            print(f"❌ Không tìm thấy thư mục: {download_dir}")
            return

        files = list(download_dir.glob("*"))
        restored_count = 0
        
        for file_path in files:
            video_id = ""
            if file_path.is_dir():
                # Xử lý slideshow folder
                video_id = file_path.name.split('_')[0]
                title = f"Restored Slideshow {video_id}"
            elif file_path.suffix.lower() in ['.mp4', '.mkv', '.webm']:
                # Xử lý video file
                video_id = file_path.name.split('_')[0]
                title = f"Restored Video {video_id}"
            else:
                continue

            if len(video_id) < 4: continue
            
            # Kiểm tra xem đã có trong DB chưa
            db.execute("SELECT id FROM videos WHERE id = ?", (video_id,))
            if db.fetchone():
                continue
            
            print(f"📦 Khôi phục: {video_id}")
            db.execute(
                "INSERT INTO videos (id, source_url, source_platform, title, status, original_path) VALUES (?, ?, ?, ?, ?, ?)",
                (video_id, "restored_url", "unknown", title, "downloaded", str(file_path))
            )
            restored_count += 1
                
        # 2. Xử lý thư mục processed (nếu có)
        processed_dir = Path(settings.PROCESSED_DIR)
        if processed_dir.exists():
            processed_files = list(processed_dir.glob("processed_*"))
            for p_file in processed_files:
                parts = p_file.name.split('_')
                if len(parts) >= 2:
                    video_id = parts[1]
                    print(f"⚙️ Cập nhật trạng thái Processed: {video_id}")
                    db.execute(
                        "UPDATE videos SET status = 'processed', processed_path = ? WHERE id = ?",
                        (str(p_file), video_id)
                    )

        conn.commit()
        print(f"\n✅ THÀNH CÔNG! Đã khôi phục {restored_count} video vào thư viện.")
        print("💡 Bây giờ bạn hãy vào lại giao diện Web và nhấn F5 để xem kết quả.")
    
    except Exception as e:
        print(f"❌ Lỗi: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    sync_storage()
