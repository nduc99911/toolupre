# Hướng dẫn cài đặt ReupMaster Pro lên VPS (Ubuntu 22.04+)

Tài liệu này hướng dẫn chi tiết cách đưa Tool từ máy cá nhân lên VPS để chạy tự động 24/7.

## 1. Yêu cầu hệ thống tối thiểu
- **Hệ điều hành:** Ubuntu 22.04 LTS (Khuyên dùng)
- **Cấu hình:** 1 vCPU, 2GB RAM, 20GB SSD.
- **Công cụ:** Python 3.10+, FFmpeg, Git.

## 2. Các bước cài đặt nhanh

### Bước 1: Cài đặt thư viện hệ điều hành
Copy và chạy lệnh này để cài đặt các công cụ nền tảng và fix lỗi đồ họa (Cairo):
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv ffmpeg git curl unzip libcairo2-dev pkg-config python3-dev -y
```

### Bước 2: Cài đặt NodeJS & PM2 (Quản lý chạy ngầm)
```bash
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install pm2 -g
```

### Bước 3: Tải Code từ GitHub
```bash
cd /root
git clone https://github.com/nduc99911/toolupre.git reupmaster
cd reupmaster
```

### Bước 4: Thiết lập môi trường Python
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Bước 5: Cấu hình file .env và Thư mục
1. Tạo thư mục lưu trữ:
```bash
mkdir -p storage/downloads storage/processed storage/temp
```
2. Tạo file cấu hình:
`nano .env` -> Dán nội dung .env từ máy tính vào -> `Ctrl+O`, `Enter`, `Ctrl+X`.

## 3. Quản lý Tool bằng PM2

- **Khởi chạy Tool:** 
  ```bash
  pm2 start "venv/bin/python run.py" --name "ReupMaster"
  ```
- **Xem nhật ký (Logs) để debug:**
  ```bash
  pm2 logs ReupMaster
  ```
- **Khởi động lại Tool:**
  ```bash
  pm2 restart ReupMaster
  ```
- **Dừng Tool:**
  ```bash
  pm2 stop ReupMaster
  ```
- **Thiết lập tự bật khi VPS reset:**
  ```bash
  pm2 save
  pm2 startup
  ```

## 4. Lưu ý quan trọng cho VPS yếu (1 CPU)
- **Tự động xóa video:** Đảm bảo trong `.env` có dòng `AUTO_CLEANUP_VIDEO=true` để không bị đầy ổ cứng 20GB.
- **Tốc độ xử lý:** Vì chỉ có 1 CPU, khi Tool xử lý video (CPU load 100%), giao diện web có thể hơi chậm một chút. Đây là hiện tượng bình thường, hãy kiên nhẫn chờ 1-2 phút.
- **Cổng truy cập:** Mặc định là port `8000`. Hãy đảm bảo đã mở port này trên Firewall của VPS (`sudo ufw allow 8000`).

---
*Chúc bạn gặt hái được nhiều triệu view!*
