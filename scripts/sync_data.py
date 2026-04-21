import os
import sqlite3
from pathlib import Path

def sync_storage():
    print("🚀 Bắt đầu quét thư mục storage để khôi phục dữ liệu (Bản siêu tối giản)...")
    
    # Tự xác định đường dẫn mà không cần import config
    base_dir = Path(__file__).resolve().parent.parent
    db_path = base_dir / "storage" / "reupmaster.db"
    download_dir = base_dir / "storage" / "downloads"
    processed_dir = base_dir / "storage" / "processed"
    
    if not db_path.exists():
        print(f"❌ Không tìm thấy file database tại: {db_path}")
        return

    # Kết nối database
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    db = conn.cursor()
    
    try:
        # 1. Quét thư mục downloads
        if not download_dir.exists():
            print(f"❌ Không tìm thấy thư mục download: {download_dir}")
            return

        files = list(download_dir.glob("*"))
        restored_count = 0
        
        for file_path in files:
            video_id = ""
            if file_path.is_dir():
                video_id = file_path.name.split('_')[0]
                title = f"Restored Slideshow {video_id}"
            elif file_path.suffix.lower() in ['.mp4', '.mkv', '.webm']:
                video_id = file_path.name.split('_')[0]
                title = f"Restored Video {video_id}"
            else:
                continue

            if len(video_id) < 4: continue
            
            # Kiểm tra xem đã có trong DB chưa
            db.execute("SELECT id FROM videos WHERE id = ?", (video_id,))
            if db.fetchone(): continue
            
            print(f"📦 Khôi phục: {video_id}")
            import datetime
            now = datetime.datetime.now().isoformat()
            db.execute(
                "INSERT INTO videos (id, source_url, source_platform, title, status, original_path, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (video_id, "restored_url", "unknown", title, "downloaded", str(file_path), now, now)
            )
            restored_count += 1
                
        # 2. Cập nhật trạng thái đã xử lý
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
    except Exception as e:
        print(f"❌ Lỗi: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    sync_storage()
