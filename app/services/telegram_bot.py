import asyncio
import os
import json
import logging
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, TelegramObject
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.config import settings
from app import database as db
from app.services.downloader import download_video
from app.services.process_queue import process_queue
from app.services.facebook_api import FacebookAPI
from app.services.video_processor import VideoProcessor

logger = logging.getLogger("reupmaster.telegram")

class PublishFlow(StatesGroup):
    waiting_for_caption = State()

bot = Bot(token=settings.TELEGRAM_BOT_TOKEN) if settings.TELEGRAM_BOT_TOKEN else None
dp = Dispatcher()
user_sessions = {}


def _is_admin(user_id: int) -> bool:
    """Check if a Telegram user ID is in the admin whitelist.
    If TELEGRAM_ALLOWED_USERS is empty, everyone is admin (backward compatible).
    """
    allowed_users = settings.TELEGRAM_ALLOWED_USERS
    if not allowed_users:
        return True  # No whitelist configured = everyone is admin
    try:
        allowed_ids = [int(x.strip()) for x in allowed_users.split(",") if x.strip()]
    except Exception:
        return True
    return user_id in allowed_ids


async def _is_guest_allowed() -> bool:
    """Check if guest access is globally enabled in DB settings."""
    try:
        val = await db.get_setting("guest_access_enabled", "true")
        return val == "true"
    except Exception:
        return True


# ═══════════════════════════════════════════
# /start - Main Menu
# ═══════════════════════════════════════════
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id

    if _is_admin(user_id):
        # Admin: Full menu
        guest_allowed = await _is_guest_allowed()
        guest_text = "🟢 Khách dùng bot: BẬT" if guest_allowed else "🔴 Khách dùng bot: TẮT"
        
        keyboard = [
            [InlineKeyboardButton(text="🎬 Tải & Reup Video/Ảnh", callback_data="menu_reup")],
            [InlineKeyboardButton(text="📚 Thư viện media", callback_data="menu_library")],
            [InlineKeyboardButton(text="📄 Danh sách Fanpage", callback_data="menu_pages")],
            [InlineKeyboardButton(text=guest_text, callback_data="admin_toggle_guest")],
            [
                InlineKeyboardButton(text="📊 Thống kê", callback_data="menu_stats"),
                InlineKeyboardButton(text="❓ Hướng dẫn", callback_data="menu_help")
            ],
        ]
        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await message.answer(
            "👋 **ReupMaster Pro Bot**\n\n"
            "Chọn tính năng bạn muốn sử dụng:",
            reply_markup=markup, parse_mode="Markdown"
        )
    else:
        # Check if guest access is disabled
        if not await _is_guest_allowed():
            await message.answer("⚠️ **Bot đang bảo trì.**\n\nHiện tại tính năng cho người dùng thông thường tạm đóng. Vui lòng quay lại sau!")
            return
            
        # Guest: Simple Reup and Help menu
        keyboard = [
            [InlineKeyboardButton(text="🎬 Tải & Reup Video/Ảnh", callback_data="menu_reup")],
            [InlineKeyboardButton(text="❓ Hướng dẫn sử dụng", callback_data="menu_help")],
        ]
        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
        await message.answer(
            "👋 **Chào bạn đến với ReupMaster Pro Bot!**\n\n"
            "Chọn tính năng bạn muốn sử dụng bên dưới hoặc gửi trực tiếp đường link video/ảnh để bắt đầu tải & lách bản quyền:",
            reply_markup=markup, parse_mode="Markdown"
        )


# ═══════════════════════════════════════════
# Menu Callbacks
# ═══════════════════════════════════════════
@dp.callback_query(F.data == "menu_reup")
async def menu_reup(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎬 **Tải & Reup Video/Ảnh**\n\n"
        "Gửi cho tôi link từ các nền tảng:\n"
        "• TikTok / Douyin\n"
        "• RedNote (Xiaohongshu)\n"
        "• Facebook Reels\n"
        "• Shopee Video\n\n"
        "Tôi sẽ tự động tải → Hỏi bạn chọn tính năng reup → Xử lý → Đăng lên Fanpage!",
        parse_mode="Markdown"
    )


@dp.callback_query(F.data == "admin_toggle_guest")
async def handle_toggle_guest(callback: CallbackQuery):
    user_id = callback.from_user.id
    if not _is_admin(user_id):
        await callback.answer("⚠️ Tính năng này chỉ dành cho Admin.", show_alert=True)
        return
        
    current = await _is_guest_allowed()
    new_val = "false" if current else "true"
    await db.set_setting("guest_access_enabled", new_val)
    
    # Update current message keyboard
    guest_text = "🟢 Khách dùng bot: BẬT" if new_val == "true" else "🔴 Khách dùng bot: TẮT"
    
    keyboard = [
        [InlineKeyboardButton(text="🎬 Tải & Reup Video/Ảnh", callback_data="menu_reup")],
        [InlineKeyboardButton(text="📚 Thư viện media", callback_data="menu_library")],
        [InlineKeyboardButton(text="📄 Danh sách Fanpage", callback_data="menu_pages")],
        [InlineKeyboardButton(text=guest_text, callback_data="admin_toggle_guest")],
        [
            InlineKeyboardButton(text="📊 Thống kê", callback_data="menu_stats"),
            InlineKeyboardButton(text="❓ Hướng dẫn", callback_data="menu_help")
        ],
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await callback.message.edit_reply_markup(reply_markup=markup)
    await callback.answer(f"Đã {'BẬT' if new_val == 'true' else 'TẮT'} quyền truy cập của khách!")


@dp.callback_query(F.data == "menu_library")
async def menu_library(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⚠️ Tính năng này chỉ dành cho Admin.", show_alert=True)
        return
    stats = await db.get_stats()
    total = stats.get("total_videos", 0)
    downloaded = stats.get("downloaded", 0)
    processed = stats.get("processed", 0)
    published = stats.get("published", 0)
    await callback.message.edit_text(
        f"📚 **Thư viện Media**\n\n"
        f"📦 Tổng: **{total}**\n"
        f"📥 Đã tải: **{downloaded}**\n"
        f"⚙️ Đã xử lý: **{processed}**\n"
        f"✅ Đã đăng: **{published}**\n\n"
        f"_Truy cập Web để xem chi tiết._",
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "menu_pages")
async def menu_pages(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⚠️ Tính năng này chỉ dành cho Admin.", show_alert=True)
        return
    pages = await db.get_all_fb_pages()
    text = "📄 **Danh sách Fanpage & Kênh**\n\n"
    if not pages:
        text += "❌ Chưa có Fanpage hoặc Kênh nào được liên kết.\n\n"
    else:
        for i, p in enumerate(pages, 1):
            name_escaped = p['page_name'].replace('_', '\\_').replace('*', '\\*')
            text += f"{i}. **{name_escaped}** ({p.get('category', 'Page')})\n"
        text += "\n"
    
    text += "💡 **Cách liên kết thêm trực tiếp:**\n"
    text += "1️⃣ Gửi **Facebook User Access Token** (bắt đầu bằng `EA...`) để tự động quét & nạp toàn bộ Fanpage của bạn.\n"
    text += "2️⃣ Gửi `tele:<tên_kênh>` (ví dụ: `tele:@my_channel` hoặc `tele:-10012345678`) để liên kết kênh Telegram làm nơi Reup."
    await callback.message.edit_text(text, parse_mode="Markdown")

@dp.callback_query(F.data == "menu_stats")
async def menu_stats(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        await callback.answer("⚠️ Tính năng này chỉ dành cho Admin.", show_alert=True)
        return
    stats = await db.get_stats()
    await callback.message.edit_text(
        f"📊 **Thống kê hệ thống**\n\n"
        f"📦 Tổng media: **{stats.get('total_videos', 0)}**\n"
        f"📥 Đã tải: **{stats.get('downloaded', 0)}**\n"
        f"⚙️ Đã xử lý: **{stats.get('processed', 0)}**\n"
        f"✅ Đã đăng: **{stats.get('published', 0)}**\n"
        f"❌ Lỗi: **{stats.get('failed', 0)}**",
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "menu_help")
async def menu_help(callback: CallbackQuery):
    await callback.message.edit_text(
        "❓ **Hướng dẫn sử dụng**\n\n"
        "1️⃣ Gửi link video/ảnh từ TikTok, RedNote, FB...\n"
        "2️⃣ Bot tự động tải về\n"
        "3️⃣ Chọn các tính năng lách bản quyền (Lật, Noise, Ghost...)\n"
        "4️⃣ Bấm **Bắt đầu xử lý**\n"
        "5️⃣ Chọn Fanpage → Nhập Caption → Đăng!\n\n"
        "📌 Lệnh:\n"
        "• /start - Menu chính\n"
        "• /skip - Bỏ qua caption khi đăng",
        parse_mode="Markdown"
    )


# ═══════════════════════════════════════════
# Handle Tokens (Facebook & Telegram Channels)
# ═══════════════════════════════════════════
@dp.message(F.text.startswith("EA") | F.text.startswith("tele:"))
async def handle_tokens(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await message.answer("⚠️ Tính năng này chỉ dành cho Admin.")
        return
    token = message.text.strip()
    msg = await message.answer("🔄 Đang xử lý Token...")
    try:
        import uuid
        if token.startswith("tele:"):
            chat_id = token.replace("tele:", "").strip()
            page_data = {
                "id": str(uuid.uuid4())[:8],
                "page_id": token,
                "page_name": f"Telegram: {chat_id}",
                "access_token": "telegram_bot",
                "category": "Telegram Channel",
                "is_active": 1,
            }
            existing = await db.get_all_fb_pages()
            for p in existing:
                if p["page_id"] == token:
                    await msg.edit_text(f"✅ Kênh Telegram {chat_id} đã tồn tại trong hệ thống!")
                    return
            await db.create_fb_page(page_data)
            await msg.edit_text(f"✅ Đã thêm Kênh Telegram: {chat_id} vào danh sách Fanpage thành công!")
            return

        # It's a Facebook Token
        from app.services.facebook_api import FacebookAPI
        long_token = await FacebookAPI.extend_token(token)
        pages = await FacebookAPI.get_user_pages(long_token)
        
        if pages and "error" in pages[0]:
            await msg.edit_text(f"❌ Lỗi Token: {pages[0]['error']}")
            return
            
        existing_pages = await db.get_all_fb_pages()
        existing_map = {p["page_id"]: p for p in existing_pages}
        
        saved = 0
        updated = 0
        for page in pages:
            if page["page_id"] in existing_map:
                db_page = existing_map[page["page_id"]]
                await db.update_fb_page(db_page["id"], {
                    "access_token": page["access_token"],
                    "page_name": page["page_name"],
                    "is_active": 1
                })
                updated += 1
            else:
                page_data = {
                    "id": str(uuid.uuid4())[:8],
                    "page_id": page["page_id"],
                    "page_name": page["page_name"],
                    "access_token": page["access_token"],
                    "category": page.get("category", ""),
                    "is_active": 1,
                }
                await db.create_fb_page(page_data)
                saved += 1
                
        await msg.edit_text(f"✅ Thành công!\n\n🆕 Thêm mới: {saved} Page\n🔄 Cập nhật: {updated} Page\n\nBạn có thể gửi link video để bắt đầu Reup.")
    except Exception as e:
        logger.error(f"Telegram token error: {e}")
        await msg.edit_text(f"❌ Lỗi hệ thống: {e}")


# ═══════════════════════════════════════════
# Handle Direct Media Uploads (Video, Photo, Document)
# ═══════════════════════════════════════════
@dp.message(F.video)
async def handle_uploaded_video(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not _is_admin(user_id):
        await message.answer("⚠️ Tính năng upload video chỉ dành cho Admin.")
        return
    import uuid
    video_id = str(uuid.uuid4())[:8]
    
    msg = await message.answer("📥 **Đang tải video của bạn từ Telegram...**", parse_mode="Markdown")
    
    try:
        dest_filename = f"{video_id}_uploaded.mp4"
        dest_path = os.path.join(settings.DOWNLOAD_DIR, dest_filename)
        os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
        
        await bot.download(message.video, destination=dest_path)
        
        from app.services.downloader import probe_video
        probe_info = await probe_video(dest_path)
        file_size = os.path.getsize(dest_path)
        
        video_data = {
            "id": video_id,
            "source_url": "telegram_upload",
            "source_platform": "telegram",
            "status": "downloaded",
            "title": message.video.file_name or f"Telegram Video {video_id}",
            "description": message.caption or "",
            "original_path": dest_path,
            "original_filename": dest_filename,
            "thumbnail_path": "",
            "file_size": file_size,
            "duration": probe_info.get("duration", message.video.duration or 0),
            "width": probe_info.get("width", message.video.width or 0),
            "height": probe_info.get("height", message.video.height or 0),
        }
        await db.create_video(video_data)
        
        user_sessions[user_id] = {
            "url": "telegram_upload",
            "video_id": video_id,
            "options": {"watermark_text": "ReupMaster"}
        }
        await send_process_options(msg, user_id)
        
    except Exception as e:
        logger.error(f"Failed to handle uploaded video: {e}")
        await msg.edit_text(f"❌ **Lỗi tải video:** {str(e)}", parse_mode="Markdown")


@dp.message(F.photo)
async def handle_uploaded_photo(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not _is_admin(user_id):
        await message.answer("⚠️ Tính năng upload ảnh chỉ dành cho Admin.")
        return
    import uuid
    video_id = str(uuid.uuid4())[:8]
    
    msg = await message.answer("📥 **Đang tải ảnh của bạn từ Telegram...**", parse_mode="Markdown")
    
    try:
        album_dir = os.path.join(settings.DOWNLOAD_DIR, f"{video_id}_images")
        os.makedirs(album_dir, exist_ok=True)
        
        photo = message.photo[-1]
        dest_filename = f"photo_{video_id}.jpg"
        dest_path = os.path.join(album_dir, dest_filename)
        
        await bot.download(photo, destination=dest_path)
        
        await db.create_video({
            "id": video_id,
            "source_url": "telegram_upload",
            "source_platform": "telegram",
            "status": "downloaded",
            "title": f"Ảnh Telegram {video_id}",
            "description": message.caption or "",
            "original_path": album_dir,
            "thumbnail_path": dest_path,
            "original_filename": "telegram_images",
            "duration": 0,
            "file_size": os.path.getsize(dest_path)
        })
        
        user_sessions[user_id] = {
            "url": "telegram_upload",
            "video_id": video_id,
            "options": {"watermark_text": "ReupMaster"}
        }
        await send_process_options(msg, user_id)
        
    except Exception as e:
        logger.error(f"Failed to handle uploaded photo: {e}")
        await msg.edit_text(f"❌ **Lỗi tải ảnh:** {str(e)}", parse_mode="Markdown")


@dp.message(F.document)
async def handle_uploaded_document(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not _is_admin(user_id):
        await message.answer("⚠️ Tính năng upload file chỉ dành cho Admin.")
        return
    mime_type = message.document.mime_type or ""
    file_name = message.document.file_name or ""
    
    is_video = mime_type.startswith("video/") or file_name.lower().endswith((".mp4", ".mkv", ".mov", ".avi", ".3gp", ".webm"))
    is_image = mime_type.startswith("image/") or file_name.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp"))
    
    if not is_video and not is_image:
        await message.answer("⚠️ File không được hỗ trợ. Vui lòng chỉ gửi video hoặc hình ảnh.")
        return
        
    import uuid
    video_id = str(uuid.uuid4())[:8]
    msg = await message.answer("📥 **Đang tải file từ Telegram...**", parse_mode="Markdown")
    
    try:
        os.makedirs(settings.DOWNLOAD_DIR, exist_ok=True)
        
        if is_video:
            dest_filename = f"{video_id}_uploaded.mp4"
            dest_path = os.path.join(settings.DOWNLOAD_DIR, dest_filename)
            await bot.download(message.document, destination=dest_path)
            
            from app.services.downloader import probe_video
            probe_info = await probe_video(dest_path)
            file_size = os.path.getsize(dest_path)
            
            video_data = {
                "id": video_id,
                "source_url": "telegram_upload",
                "source_platform": "telegram",
                "status": "downloaded",
                "title": file_name or f"Telegram Video {video_id}",
                "description": message.caption or "",
                "original_path": dest_path,
                "original_filename": dest_filename,
                "thumbnail_path": "",
                "file_size": file_size,
                "duration": probe_info.get("duration", 0),
                "width": probe_info.get("width", 0),
                "height": probe_info.get("height", 0),
            }
            await db.create_video(video_data)
            
            user_sessions[user_id] = {
                "url": "telegram_upload",
                "video_id": video_id,
                "options": {"watermark_text": "ReupMaster"}
            }
            await send_process_options(msg, user_id)
            
        elif is_image:
            album_dir = os.path.join(settings.DOWNLOAD_DIR, f"{video_id}_images")
            os.makedirs(album_dir, exist_ok=True)
            
            dest_filename = file_name or f"image_{video_id}.jpg"
            dest_path = os.path.join(album_dir, dest_filename)
            await bot.download(message.document, destination=dest_path)
            
            await db.create_video({
                "id": video_id,
                "source_url": "telegram_upload",
                "source_platform": "telegram",
                "status": "downloaded",
                "title": f"Bộ ảnh Telegram ({file_name})",
                "description": message.caption or "",
                "original_path": album_dir,
                "thumbnail_path": dest_path,
                "original_filename": "telegram_images",
                "duration": 0,
                "file_size": os.path.getsize(dest_path)
            })
            
            user_sessions[user_id] = {
                "url": "telegram_upload",
                "video_id": video_id,
                "options": {"watermark_text": "ReupMaster"}
            }
            await send_process_options(msg, user_id)
            
    except Exception as e:
        logger.error(f"Failed to handle uploaded document: {e}")
        await msg.edit_text(f"❌ **Lỗi tải file:** {str(e)}", parse_mode="Markdown")


# ═══════════════════════════════════════════
# Handle URL - Ask Video or Image
# ═══════════════════════════════════════════
@dp.message(F.text.regexp(r'(https?://[^\s]+)'))
async def handle_url(message: Message, state: FSMContext):
    url = message.text.strip()
    
    # Save URL to session
    user_sessions[message.from_user.id] = {
        "url": url,
        "options": {"watermark_text": "ReupMaster"}
    }
    
    # Check if it's a profile URL
    is_douyin_profile = "douyin.com/user/" in url
    is_rednote_profile = "rednote.com/user/" in url or "xiaohongshu.com/user/" in url
    
    if is_rednote_profile:
        await message.answer("⚠️ Bot hiện chưa hỗ trợ quét nguyên Profile RedNote. Vui lòng sử dụng Crawler trên máy tính hoặc gửi từng link bài viết riêng lẻ.")
        return

    is_admin = _is_admin(message.from_user.id)
    if not is_admin and not await _is_guest_allowed():
        await message.answer("⚠️ **Bot đang bảo trì.**\n\nHiện tại tính năng cho người dùng thông thường tạm đóng. Vui lòng quay lại sau!")
        return

    keyboard = []
    if is_douyin_profile:
        if is_admin:
            keyboard.append([InlineKeyboardButton(text="🕵️ Quét Profile Douyin", callback_data="dl_profile_douyin")])
            msg_text = "📎 Đã nhận link Profile!\n\nBạn muốn quét toàn bộ video từ kênh này?"
        else:
            await message.answer("⚠️ Tính năng quét Profile chỉ dành cho Admin. Vui lòng gửi link bài viết/video đơn lẻ.")
            return
    else:
        keyboard.extend([
            [InlineKeyboardButton(text="🎬 Tải Video", callback_data="dl_video")],
            [InlineKeyboardButton(text="🖼️ Tải Bộ ảnh", callback_data="dl_images")],
        ])
        msg_text = "📎 Đã nhận link!\n\nBạn muốn tải dạng nào?"
        
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer(msg_text, reply_markup=markup)

@dp.callback_query(F.data == "dl_profile_douyin")
async def handle_dl_profile_douyin(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_sessions or "url" not in user_sessions[user_id]:
        await callback.message.edit_text("❌ Session đã hết hạn.")
        return
        
    url = user_sessions[user_id]["url"]
    await callback.message.edit_text("⏳ Đang khởi động Crawler quét Profile Douyin... (có thể mất 1-2 phút)")
    
    try:
        from app.services.douyin_service import douyin_service
        profile_data = await douyin_service.get_profile(url, count=20)
        
        if "error" in profile_data:
            await callback.message.edit_text(f"❌ Lỗi quét Profile: {profile_data['error']}")
            return
            
        data = profile_data.get("data", {})
        userInfo = data.get("userInfo", {})
        videos = data.get("videos", [])
        
        if not videos:
            await callback.message.edit_text("❌ Không tìm thấy video nào trên kênh này.")
            return
            
        # Store videos in session to allow downloading them later
        user_sessions[user_id]["profile_videos"] = videos
        
        text = f"👤 **Kênh:** {userInfo.get('nickname', 'Unknown')}\n"
        text += f"📦 **Tìm thấy:** {len(videos)} videos\n\n"
        text += "Chọn số lượng video muốn tải về (từ mới nhất):"
        
        kb = [
            [
                InlineKeyboardButton(text="Tải 5 video đầu", callback_data="dl_prof_vids_5"),
                InlineKeyboardButton(text="Tải 10 video", callback_data="dl_prof_vids_10")
            ],
            [InlineKeyboardButton(text=f"Tải tất cả ({len(videos)})", callback_data=f"dl_prof_vids_{len(videos)}")]
        ]
        
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Telegram profile scan error: {e}")
        await callback.message.edit_text(f"❌ Lỗi hệ thống: {e}")

@dp.callback_query(F.data.startswith("dl_prof_vids_"))
async def handle_dl_profile_videos(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_sessions or "profile_videos" not in user_sessions[user_id]:
        await callback.message.edit_text("❌ Session đã hết hạn.")
        return
        
    count_str = callback.data.replace("dl_prof_vids_", "")
    count = int(count_str)
    
    videos = user_sessions[user_id]["profile_videos"][:count]
    await callback.message.edit_text(f"⏳ Đang xếp {len(videos)} video vào hàng đợi tải xuống...")
    
    import uuid
    from app.services.downloader import download_video
    
    for vid in videos:
        # Tải ngầm hoặc gửi link cho downloader
        url = f"https://www.douyin.com/video/{vid.get('id')}"
        video_id = str(uuid.uuid4())[:8]
        
        await db.create_video({
            "id": video_id,
            "source_url": url,
            "source_platform": "douyin",
            "status": "downloading"
        })
        
        # Tạo task chạy ngầm
        import asyncio
        asyncio.create_task(download_video(url, video_id=video_id))
        
        # Gửi thông báo ngắn cho người dùng
        await bot.send_message(user_id, f"📥 Đang tải: {vid.get('desc', '')[:30]}...")
        await asyncio.sleep(1)
        
    await bot.send_message(user_id, f"✅ Đã đưa {len(videos)} video vào tiến trình tải ngầm. Bạn có thể kiểm tra ở Web UI hoặc nhắn link mới!")


@dp.callback_query(F.data == "dl_video")
async def handle_dl_video(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_sessions or "url" not in user_sessions[user_id]:
        await callback.message.edit_text("❌ Session đã hết hạn.")
        return
    
    url = user_sessions[user_id]["url"]
    await callback.message.edit_text("⏳ Đang tải Video...")
    
    try:
        import uuid
        from app.services.downloader import detect_platform
        video_id = str(uuid.uuid4())[:8]
        platform = detect_platform(url)
        
        await db.create_video({
            "id": video_id,
            "source_url": url,
            "source_platform": platform,
            "status": "downloading"
        })
        
        result = await download_video(url, video_id=video_id)
        if "error" in result:
            await callback.message.edit_text(f"❌ Lỗi tải video: {result.get('error')}")
            return
        
        user_sessions[user_id]["video_id"] = video_id
        await send_process_options(callback.message, user_id)
    except Exception as e:
        logger.error(f"Telegram dl_video error: {e}")
        await callback.message.edit_text(f"❌ Lỗi: {str(e)}")


@dp.callback_query(F.data == "dl_video_guest")
async def handle_dl_video_guest(callback: CallbackQuery, state: FSMContext):
    """Guest mode: Download video and send directly, no processing/reup."""
    user_id = callback.from_user.id
    if user_id not in user_sessions or "url" not in user_sessions[user_id]:
        await callback.message.edit_text("❌ Session đã hết hạn. Vui lòng gửi lại link.")
        return

    url = user_sessions[user_id]["url"]
    await callback.message.edit_text("⏳ Đang tải Video cho bạn...")

    try:
        import uuid
        from app.services.downloader import detect_platform
        video_id = str(uuid.uuid4())[:8]
        platform = detect_platform(url)

        await db.create_video({
            "id": video_id,
            "source_url": url,
            "source_platform": platform,
            "status": "downloading"
        })

        result = await download_video(url, video_id=video_id)
        if "error" in result:
            await callback.message.edit_text(f"❌ Lỗi tải video: {result.get('error')}")
            return

        # Get downloaded video info
        video = await db.get_video(video_id)
        video_path = video.get("original_path", "") if video else ""

        if not video_path or not os.path.isfile(video_path):
            await callback.message.edit_text("❌ Không tìm thấy file video sau khi tải.")
            return

        file_size = os.path.getsize(video_path)
        if file_size > 50 * 1024 * 1024:
            await callback.message.edit_text(
                "✅ Tải xong!\n⚠️ File quá lớn (>50MB) để gửi qua Telegram.\n"
                "Vui lòng liên hệ Admin để tải video này."
            )
            return

        await callback.message.edit_text("✅ Tải xong! Đang gửi video...")

        from aiogram.types import FSInputFile
        title = video.get("title", "Video") if video else "Video"
        await bot.send_video(
            user_id, FSInputFile(video_path),
            caption=f"🎬 {title}"
        )

        # Cleanup: delete downloaded file to save VPS space
        try:
            os.remove(video_path)
            await db.delete_video(video_id)
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Telegram dl_video_guest error: {e}")
        await callback.message.edit_text(f"❌ Lỗi: {str(e)}")


@dp.callback_query(F.data == "dl_images")
async def handle_dl_images(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_sessions or "url" not in user_sessions[user_id]:
        await callback.message.edit_text("❌ Session đã hết hạn.")
        return
    
    url = user_sessions[user_id]["url"]
    await callback.message.edit_text("⏳ Đang tải Bộ ảnh...")
    
    try:
        from app.services.image_downloader import download_images_from_url
        img_result = await download_images_from_url(url)
        if img_result.get("error") or not img_result.get("images"):
            await callback.message.edit_text(f"❌ Lỗi tải ảnh: {img_result.get('error', 'Không tìm thấy ảnh')}")
            return
        
        video_id = img_result["id"]
        thumbnail = img_result["images"][0]
        await db.create_video({
            "id": video_id, "source_url": url,
            "source_platform": img_result["platform"], "status": "downloaded",
            "title": f"Bộ ảnh {img_result['platform']} ({len(img_result['images'])} ảnh)",
            "original_path": img_result["save_dir"], "thumbnail_path": thumbnail,
            "original_filename": f"{img_result['platform']}_images",
            "duration": 0, "file_size": 0
        })
        
        user_sessions[user_id]["video_id"] = video_id
        await send_process_options(callback.message, user_id)
    except Exception as e:
        logger.error(f"Telegram dl_images error: {e}")
        await callback.message.edit_text(f"❌ Lỗi: {str(e)}")


# ═══════════════════════════════════════════
# Process Options Menu (Dynamic from VideoProcessor)
# ═══════════════════════════════════════════
async def send_process_options(msg, user_id):
    session = user_sessions.get(user_id)
    if not session:
        return
    opts = session["options"]

    keyboard = []
    row = []
    for key, info in VideoProcessor.AVAILABLE_OPTIONS.items():
        is_on = opts.get(key, info.get("default", False))
        name = info["name"]
        if len(name) > 18:
            name = name[:16] + ".."
        btn_text = f"{'✅ ' if is_on else '❌ '}{name}"
        row.append(InlineKeyboardButton(text=btn_text, callback_data=f"opt_t_{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton(text="🎙️ VIETSUB + LỒNG TIẾNG", callback_data="opt_vietsub")])
    keyboard.append([InlineKeyboardButton(text="📝 VIETSUB (CHỈ PHỤ ĐỀ)", callback_data="opt_vietsub_only")])
    keyboard.append([InlineKeyboardButton(text="⚡ BẮT ĐẦU XỬ LÝ ⚡", callback_data="opt_start")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await msg.edit_text(
        "✅ Tải xong!\n\n⚙️ **Chọn các tính năng lách bản quyền:**\n_(Bấm để Bật/Tắt)_",
        reply_markup=markup, parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("opt_t_"))
async def handle_toggle_option(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_sessions:
        await callback.message.edit_text("❌ Session đã hết hạn.")
        return
    key = callback.data.replace("opt_t_", "")
    opts = user_sessions[user_id]["options"]
    default_val = VideoProcessor.AVAILABLE_OPTIONS.get(key, {}).get("default", False)
    opts[key] = not opts.get(key, default_val)
    
    # Mutual exclusivity for Vietsub options
    if key == "vietsub_dubbing" and opts[key]:
        opts["vietsub_only"] = False
    elif key == "vietsub_only" and opts[key]:
        opts["vietsub_dubbing"] = False

    if key == "mirror":
        opts["flip"] = opts["mirror"]
    elif key == "add_watermark_text":
        opts["watermark"] = opts["add_watermark_text"]
    await send_process_options(callback.message, user_id)


@dp.callback_query(F.data == "opt_vietsub_only")
async def handle_vietsub_only(callback: CallbackQuery, state: FSMContext):
    """Run Vietsub subtitle-only pipeline (no voiceover)."""
    user_id = callback.from_user.id
    if user_id not in user_sessions:
        await callback.message.edit_text("❌ Session đã hết hạn.")
        return

    video_id = user_sessions[user_id].get("video_id")
    if not video_id:
        await callback.message.edit_text("❌ Không tìm thấy video.")
        return

    await callback.message.edit_text(
        "📝 **VIETSUB (CHỈ PHỤ ĐỀ)**\n\n"
        "⏳ Đang chạy pipeline AI...\n"
        "1️⃣ Tách âm thanh...\n"
        "2️⃣ Nhận dạng giọng nói (Whisper)...\n"
        "3️⃣ Dịch sang Tiếng Việt (AI)...\n"
        "4️⃣ Burn phụ đề lên video...\n\n"
        "⏱ Quá trình này mất 1-3 phút, vui lòng chờ.",
        parse_mode="Markdown"
    )

    try:
        from app.services.vietsub_service import full_vietsub_pipeline

        video = await db.get_video(video_id)
        if not video:
            await callback.message.edit_text("❌ Video không tồn tại.")
            return

        video_path = video.get("original_path")
        if not video_path or not os.path.exists(video_path):
            await callback.message.edit_text("❌ File video không tồn tại trên ổ đĩa.")
            return

        result = await full_vietsub_pipeline(
            video_path=video_path,
            include_voiceover=False,
            include_subtitles=True,
            original_volume=1.0,  # Keep original audio
        )

        if "error" in result:
            await callback.message.edit_text(
                f"❌ **Vietsub thất bại:**\n{result['error']}",
                parse_mode="Markdown"
            )
            return

        await db.update_video(video_id, {
            "status": "processed",
            "processed_path": result["output_path"],
        })

        output_path = result["output_path"]
        lang = result.get("source_lang", "?")
        segs = result.get("segment_count", 0)

        await callback.message.edit_text(
            f"✅ **Vietsub phụ đề hoàn tất!**\n\n"
            f"🌍 Ngôn ngữ gốc: **{lang}**\n"
            f"📝 Số câu phụ đề: **{segs}**\n"
            f"🔊 Âm thanh gốc: Giữ nguyên\n\n"
            f"⏳ Đang gửi video...",
            parse_mode="Markdown"
        )

        from aiogram.types import FSInputFile
        file_size = os.path.getsize(output_path)
        if file_size > 50 * 1024 * 1024:
            await bot.send_message(user_id, "⚠️ File quá lớn (>50MB), hãy tải từ Web UI.")
        else:
            await bot.send_video(
                user_id, FSInputFile(output_path),
                caption=f"📝 Video đã Vietsub (chỉ phụ đề)\n🌍 {lang} → vi | {segs} câu"
            )

        # For guest, cleanup files to save VPS space
        if not _is_admin(user_id):
            try:
                if output_path and os.path.exists(output_path):
                    os.remove(output_path)
                orig_path = video.get("original_path")
                if orig_path and os.path.exists(orig_path):
                    os.remove(orig_path)
                await db.delete_video(video_id)
            except Exception as e:
                logger.warning(f"Failed to cleanup guest vietsub-only files: {e}")
                
            if user_id in user_sessions:
                del user_sessions[user_id]

    except Exception as e:
        logger.error(f"Telegram vietsub-only error: {e}")
        await callback.message.edit_text(f"❌ Lỗi hệ thống: {e}")


@dp.callback_query(F.data == "opt_vietsub")
async def handle_vietsub(callback: CallbackQuery, state: FSMContext):
    """Run full Vietsub + Lồng Tiếng pipeline from Telegram."""
    user_id = callback.from_user.id
    if user_id not in user_sessions:
        await callback.message.edit_text("❌ Session đã hết hạn.")
        return

    video_id = user_sessions[user_id].get("video_id")
    if not video_id:
        await callback.message.edit_text("❌ Không tìm thấy video.")
        return

    await callback.message.edit_text(
        "🎙️ **VIETSUB + LỒNG TIẾNG**\n\n"
        "⏳ Đang chạy pipeline AI...\n"
        "1️⃣ Tách âm thanh...\n"
        "2️⃣ Nhận dạng giọng nói (Whisper)...\n"
        "3️⃣ Dịch sang Tiếng Việt (AI)...\n"
        "4️⃣ Lồng tiếng Việt (Edge-TTS)...\n"
        "5️⃣ Render video cuối cùng...\n\n"
        "⏱ Quá trình này mất 2-5 phút, vui lòng chờ.",
        parse_mode="Markdown"
    )

    try:
        from app.services.vietsub_service import full_vietsub_pipeline

        video = await db.get_video(video_id)
        if not video:
            await callback.message.edit_text("❌ Video không tồn tại.")
            return

        video_path = video.get("original_path")
        if not video_path or not os.path.exists(video_path):
            await callback.message.edit_text("❌ File video không tồn tại trên ổ đĩa.")
            return

        result = await full_vietsub_pipeline(
            video_path=video_path,
            include_voiceover=True,
            include_subtitles=True,
        )

        if "error" in result:
            await callback.message.edit_text(
                f"❌ **Vietsub thất bại:**\n{result['error']}\n\n"
                f"📊 Steps: {json.dumps(result.get('steps', {}), ensure_ascii=False, indent=1)}",
                parse_mode="Markdown"
            )
            return

        # Update DB
        await db.update_video(video_id, {
            "status": "processed",
            "processed_path": result["output_path"],
        })

        output_path = result["output_path"]
        lang = result.get("source_lang", "?")
        segs = result.get("segment_count", 0)

        await callback.message.edit_text(
            f"✅ **Vietsub + Lồng tiếng hoàn tất!**\n\n"
            f"🌍 Ngôn ngữ gốc: **{lang}**\n"
            f"📝 Số câu phụ đề: **{segs}**\n"
            f"📁 File: {os.path.basename(output_path).replace('_', '\\_')}\n\n"
            f"⏳ Đang gửi video...",
            parse_mode="Markdown"
        )

        # Send video to user
        from aiogram.types import FSInputFile
        file_size = os.path.getsize(output_path)
        if file_size > 50 * 1024 * 1024:
            await bot.send_message(
                user_id,
                "⚠️ File Vietsub quá lớn (>50MB) để gửi qua Telegram.\n"
                "Hãy tải từ Web UI."
            )
        else:
            await bot.send_video(
                user_id, FSInputFile(output_path),
                caption=f"🎙️ Video đã Vietsub + Lồng tiếng\n🌍 {lang} → vi | {segs} câu"
            )

        # Now ask about publishing
        is_admin = _is_admin(user_id)
        if not is_admin:
            await bot.send_message(user_id, "✅ Hoàn tất quá trình Vietsub & lồng tiếng của bạn!")
            
            # Cleanup files to save VPS space
            try:
                if output_path and os.path.exists(output_path):
                    os.remove(output_path)
                orig_path = video.get("original_path")
                if orig_path and os.path.exists(orig_path):
                    os.remove(orig_path)
                await db.delete_video(video_id)
            except Exception as e:
                logger.warning(f"Failed to cleanup guest vietsub files: {e}")
                
            if user_id in user_sessions:
                del user_sessions[user_id]
            return

        pages = await db.get_all_fb_pages()
        keyboard = []
        for p in pages:
            keyboard.append([InlineKeyboardButton(text=f"📄 {p['page_name']}", callback_data=f"page_{p['id']}")])
        keyboard.append([InlineKeyboardButton(text="✅ Chỉ tải về, không đăng", callback_data="done_skip")])
        markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

        if pages:
            await bot.send_message(
                user_id,
                "📤 Bạn muốn đăng video Vietsub lên đâu?",
                reply_markup=markup
            )
        else:
            await bot.send_message(user_id, "✅ Hoàn tất! Chưa có Fanpage nào để đăng.")

    except Exception as e:
        logger.error(f"Telegram vietsub error: {e}")
        await callback.message.edit_text(f"❌ Lỗi hệ thống: {e}")


@dp.callback_query(F.data == "opt_start")
async def handle_start_process(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id not in user_sessions:
        await callback.message.edit_text("❌ Session đã hết hạn.")
        return

    opts = user_sessions[user_id]["options"]
    video_id = user_sessions[user_id]["video_id"]
    await callback.message.edit_text("⏳ Đang xử lý lách bản quyền, vui lòng chờ...")

    await process_queue.add_videos([video_id], opts)

    # Poll for completion
    logger.info(f"Checking process status for video_id: {video_id}")
    from app.services.progress import video_progress
    last_text = ""
    for _ in range(150):  # max 5 min
        await asyncio.sleep(2)
        video = await db.get_video(video_id)
        if not video:
            logger.error(f"process_queue: video_id '{video_id}' returned None from db!")
            await callback.message.edit_text(f"❌ Không tìm thấy media trong CSDL (ID: {video_id}).")
            return
        if video.get("status") == "processed":
            break
        if video.get("status") == "failed":
            await callback.message.edit_text(f"❌ Lỗi xử lý: {video.get('error_message')}")
            return
            
        progress = video_progress.get(video_id, 0.0)
        progress_text = f"⏳ Đang xử lý lách bản quyền: {progress}%..."
        if progress_text != last_text:
            try:
                await callback.message.edit_text(progress_text)
                last_text = progress_text
            except Exception:
                pass
    else:
        await callback.message.edit_text("❌ Timeout: Xử lý quá lâu.")
        return

    # Send processed media back to user
    video = await db.get_video(video_id)
    video_path = video.get("processed_path") or video.get("original_path")
    is_image = os.path.isdir(video_path)  # Simple: directory = images, file = video

    from aiogram.types import FSInputFile
    try:
        if is_image and os.path.isdir(video_path):
            valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
            files = sorted([f for f in os.listdir(video_path)
                          if os.path.splitext(f)[1].lower() in valid_exts])
            await callback.message.edit_text(f"✅ Xử lý xong! Đang gửi {len(files)} ảnh...")
            for f in files:
                fpath = os.path.join(video_path, f)
                await bot.send_photo(callback.from_user.id, FSInputFile(fpath))
        elif os.path.isfile(video_path):
            file_size = os.path.getsize(video_path)
            if file_size > 50 * 1024 * 1024:  # > 50MB
                await callback.message.edit_text(
                    "✅ Xử lý xong!\n⚠️ File quá lớn (>50MB), không gửi qua Telegram được.\n"
                    "Hãy tải từ Web."
                )
            else:
                await callback.message.edit_text("✅ Xử lý xong! Đang gửi video...")
                await bot.send_video(callback.from_user.id, FSInputFile(video_path),
                                     caption=f"🎬 {video.get('title', 'Video đã xử lý')}")
    except Exception as e:
        logger.warning(f"Failed to send media to Telegram: {e}")

    # Ask: publish or done?
    is_admin = _is_admin(callback.from_user.id)
    if not is_admin:
        await bot.send_message(callback.from_user.id, "✅ Hoàn tất quá trình xử lý video lách bản quyền của bạn!")
        
        # Cleanup files to save VPS space
        try:
            if is_image and os.path.isdir(video_path):
                import shutil
                shutil.rmtree(video_path)
            elif os.path.isfile(video_path):
                os.remove(video_path)
            
            # Also remove original path if it exists and is different
            orig_path = video.get("original_path")
            if orig_path and os.path.exists(orig_path) and orig_path != video_path:
                if os.path.isdir(orig_path):
                    import shutil
                    shutil.rmtree(orig_path)
                elif os.path.isfile(orig_path):
                    os.remove(orig_path)
                    
            await db.delete_video(video_id)
        except Exception as e:
            logger.warning(f"Failed to cleanup guest files: {e}")
            
        # Clean session
        if callback.from_user.id in user_sessions:
            del user_sessions[callback.from_user.id]
        return

    pages = await db.get_all_fb_pages()
    keyboard = []
    for p in pages:
        keyboard.append([InlineKeyboardButton(text=f"📄 {p['page_name']}", callback_data=f"page_{p['id']}")])
    keyboard.append([InlineKeyboardButton(text="✅ Chỉ tải về, không đăng", callback_data="done_skip")])
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)

    if pages:
        await bot.send_message(
            callback.from_user.id,
            "📤 Bạn muốn đăng lên Fanpage nào?\n_(Hoặc bấm nút cuối nếu chỉ muốn tải về)_",
            reply_markup=markup, parse_mode="Markdown"
        )
    else:
        await bot.send_message(callback.from_user.id, "✅ Hoàn tất! Chưa có Fanpage nào để đăng.")


# ═══════════════════════════════════════════
# Page Selection & Caption & Publish
# ═══════════════════════════════════════════
@dp.callback_query(F.data == "done_skip")
async def handle_done_skip(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
    await callback.message.edit_text("✅ Hoàn tất! Media đã được gửi về điện thoại của bạn.")

@dp.callback_query(F.data.startswith("page_"))
async def process_page_selection(callback: CallbackQuery, state: FSMContext):
    page_db_id = callback.data.split("_")[1]
    if callback.from_user.id not in user_sessions:
        await callback.message.edit_text("❌ Session đã hết hạn, vui lòng gửi lại link.")
        return
    user_sessions[callback.from_user.id]["page_db_id"] = page_db_id
    await callback.message.edit_text(
        "📝 Đã chọn Page.\n\n"
        "Bây giờ hãy nhập Caption (nội dung) cho bài viết.\n"
        "(Hoặc gõ /skip để bỏ qua caption)"
    )
    await state.set_state(PublishFlow.waiting_for_caption)


@dp.message(PublishFlow.waiting_for_caption)
async def process_caption(message: Message, state: FSMContext):
    caption = "" if message.text == "/skip" else message.text
    user_id = message.from_user.id
    if user_id not in user_sessions:
        await message.answer("❌ Session đã hết hạn, vui lòng gửi lại link.")
        await state.clear()
        return

    session = user_sessions[user_id]
    video_id = session.get("video_id")
    page_db_id = session.get("page_db_id")
    msg = await message.answer("🚀 Đang tiến hành đăng bài...")

    try:
        video = await db.get_video(video_id)
        pages = await db.get_all_fb_pages()
        page = next((p for p in pages if p["id"] == page_db_id), None)
        if not video or not page:
            await msg.edit_text("❌ Dữ liệu video hoặc page không tồn tại.")
            await state.clear()
            return

        video_path = video.get("processed_path") or video.get("original_path")
        is_image = "Bộ ảnh" in video.get("title", "") or (
            video.get("duration", 1) == 0 and video.get("thumbnail_path")
            and not str(video.get("original_filename", "")).endswith(".mp4")
        )

        if is_image:
            images = []
            if os.path.isdir(video_path):
                valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
                for f in sorted(os.listdir(video_path)):
                    if os.path.splitext(f)[1].lower() in valid_exts:
                        images.append(os.path.join(video_path, f))
            result = await FacebookAPI.post_images(
                page_id=page["page_id"], access_token=page["access_token"],
                image_paths=images, caption=caption,
            )
        else:
            result = await FacebookAPI.post_video(
                page_id=page["page_id"], access_token=page["access_token"],
                video_path=video_path, caption=caption,
                title=video.get("ai_title") or video.get("title", ""),
            )

        if result.get("success"):
            await db.update_video(video_id, {"status": "published"})
            post_id = result.get("post_id", "")
            await msg.edit_text(f"✅ Đăng bài thành công!\n\nID Bài viết: {post_id}")
        else:
            await msg.edit_text(f"❌ Lỗi đăng bài: {result.get('error')}")

    except Exception as e:
        logger.error(f"Telegram publish error: {e}")
        await msg.edit_text(f"❌ Lỗi khi đăng: {str(e)}")

    await state.clear()
    if user_id in user_sessions:
        del user_sessions[user_id]


# ═══════════════════════════════════════════
# Bot Startup
# ═══════════════════════════════════════════
async def start_telegram_bot():
    """Start the Telegram bot polling in the background."""
    if bot:
        logger.info("Starting Telegram Bot polling...")
        try:
            from aiogram.types import BotCommand
            await bot.set_my_commands([
                BotCommand(command="start", description="Menu chính & các tính năng"),
                BotCommand(command="skip", description="Bỏ qua caption khi đăng bài"),
            ])
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")
        await dp.start_polling(bot)
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set, bot will not start.")
