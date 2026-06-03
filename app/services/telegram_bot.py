import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
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


# ═══════════════════════════════════════════
# /start - Main Menu
# ═══════════════════════════════════════════
@dp.message(Command("start"))
async def cmd_start(message: Message):
    keyboard = [
        [InlineKeyboardButton(text="🎬 Tải & Reup Video/Ảnh", callback_data="menu_reup")],
        [InlineKeyboardButton(text="📚 Thư viện media", callback_data="menu_library")],
        [InlineKeyboardButton(text="📄 Danh sách Fanpage", callback_data="menu_pages")],
        [InlineKeyboardButton(text="📊 Thống kê hệ thống", callback_data="menu_stats")],
        [InlineKeyboardButton(text="❓ Hướng dẫn sử dụng", callback_data="menu_help")],
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer(
        "👋 **ReupMaster Pro Bot**\n\n"
        "Chọn tính năng bạn muốn sử dụng:",
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

@dp.callback_query(F.data == "menu_library")
async def menu_library(callback: CallbackQuery):
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
    pages = await db.get_all_fb_pages()
    if not pages:
        await callback.message.edit_text("❌ Chưa có Fanpage nào. Hãy kết nối trên Web trước.")
        return
    text = "📄 **Danh sách Fanpage**\n\n"
    for i, p in enumerate(pages, 1):
        text += f"{i}. **{p['page_name']}** ({p.get('category', 'Page')})\n"
    await callback.message.edit_text(text, parse_mode="Markdown")

@dp.callback_query(F.data == "menu_stats")
async def menu_stats(callback: CallbackQuery):
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
    
    keyboard = [
        [InlineKeyboardButton(text="🎬 Tải Video", callback_data="dl_video")],
        [InlineKeyboardButton(text="🖼️ Tải Bộ ảnh", callback_data="dl_images")],
    ]
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    await message.answer(
        "📎 Đã nhận link!\n\nBạn muốn tải dạng nào?",
        reply_markup=markup
    )


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
    if key == "mirror":
        opts["flip"] = opts["mirror"]
    elif key == "add_watermark_text":
        opts["watermark"] = opts["add_watermark_text"]
    await send_process_options(callback.message, user_id)


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
    for _ in range(120):  # max 4 min
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
