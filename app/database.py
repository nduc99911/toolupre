"""
ReupMaster Pro - Database Module
SQLite database with async support using aiosqlite.
"""
import aiosqlite
import json
from datetime import datetime
from app.config import settings

DB_PATH = settings.DATABASE_URL

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_platform TEXT NOT NULL DEFAULT 'unknown',
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    original_filename TEXT DEFAULT '',
    original_path TEXT DEFAULT '',
    processed_path TEXT DEFAULT '',
    thumbnail_path TEXT DEFAULT '',
    duration REAL DEFAULT 0,
    width INTEGER DEFAULT 0,
    height INTEGER DEFAULT 0,
    file_size INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    ai_title TEXT DEFAULT '',
    ai_description TEXT DEFAULT '',
    processing_options TEXT DEFAULT '{}',
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fb_pages (
    id TEXT PRIMARY KEY,
    page_id TEXT NOT NULL UNIQUE,
    page_name TEXT DEFAULT '',
    access_token TEXT NOT NULL,
    category TEXT DEFAULT '',
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduled_posts (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    page_id TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,
    caption TEXT DEFAULT '',
    hashtags TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    fb_post_id TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    published_at TEXT DEFAULT '',
    FOREIGN KEY (video_id) REFERENCES videos(id),
    FOREIGN KEY (page_id) REFERENCES fb_pages(id)
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


async def get_db():
    """Get database connection."""
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    """Initialize database schema."""
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        await db.commit()
    finally:
        await db.close()


# ─── Video CRUD ───

async def create_video(video_data: dict) -> dict:
    now = datetime.utcnow().isoformat()
    video_data.setdefault("created_at", now)
    video_data.setdefault("updated_at", now)
    video_data.setdefault("status", "pending")

    db = await get_db()
    try:
        cols = ", ".join(video_data.keys())
        placeholders = ", ".join(["?" for _ in video_data])
        await db.execute(
            f"INSERT INTO videos ({cols}) VALUES ({placeholders})",
            list(video_data.values())
        )
        await db.commit()
        return video_data
    finally:
        await db.close()


async def get_video(video_id: str) -> dict | None:
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def get_all_videos(status: str = None, limit: int = 100) -> list[dict]:
    db = await get_db()
    try:
        if status:
            cursor = await db.execute(
                "SELECT * FROM videos WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM videos ORDER BY created_at DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def update_video(video_id: str, data: dict) -> bool:
    data["updated_at"] = datetime.utcnow().isoformat()
    db = await get_db()
    try:
        sets = ", ".join([f"{k} = ?" for k in data.keys()])
        await db.execute(
            f"UPDATE videos SET {sets} WHERE id = ?",
            list(data.values()) + [video_id]
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def delete_video(video_id: str) -> bool:
    db = await get_db()
    try:
        await db.execute("DELETE FROM videos WHERE id = ?", (video_id,))
        await db.commit()
        return True
    finally:
        await db.close()


# ─── Facebook Pages CRUD ───

async def create_fb_page(page_data: dict) -> dict:
    page_data.setdefault("created_at", datetime.utcnow().isoformat())
    db = await get_db()
    try:
        cols = ", ".join(page_data.keys())
        placeholders = ", ".join(["?" for _ in page_data])
        await db.execute(
            f"INSERT OR REPLACE INTO fb_pages ({cols}) VALUES ({placeholders})",
            list(page_data.values())
        )
        await db.commit()
        return page_data
    finally:
        await db.close()


async def get_all_fb_pages() -> list[dict]:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM fb_pages WHERE is_active = 1 ORDER BY page_name"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def delete_fb_page(page_id: str) -> bool:
    db = await get_db()
    try:
        await db.execute("DELETE FROM fb_pages WHERE id = ?", (page_id,))
        await db.commit()
        return True
    finally:
        await db.close()


# ─── Scheduled Posts CRUD ───

async def create_scheduled_post(post_data: dict) -> dict:
    post_data.setdefault("created_at", datetime.utcnow().isoformat())
    post_data.setdefault("status", "pending")
    db = await get_db()
    try:
        cols = ", ".join(post_data.keys())
        placeholders = ", ".join(["?" for _ in post_data])
        await db.execute(
            f"INSERT INTO scheduled_posts ({cols}) VALUES ({placeholders})",
            list(post_data.values())
        )
        await db.commit()
        return post_data
    finally:
        await db.close()


async def get_all_scheduled_posts(status: str = None) -> list[dict]:
    db = await get_db()
    try:
        if status:
            cursor = await db.execute(
                """SELECT sp.*, v.title as video_title, v.thumbnail_path, 
                   fp.page_name FROM scheduled_posts sp
                   LEFT JOIN videos v ON sp.video_id = v.id
                   LEFT JOIN fb_pages fp ON sp.page_id = fp.id
                   WHERE sp.status = ? ORDER BY sp.scheduled_time""",
                (status,)
            )
        else:
            cursor = await db.execute(
                """SELECT sp.*, v.title as video_title, v.thumbnail_path,
                   fp.page_name FROM scheduled_posts sp
                   LEFT JOIN videos v ON sp.video_id = v.id
                   LEFT JOIN fb_pages fp ON sp.page_id = fp.id
                   ORDER BY sp.scheduled_time"""
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def update_scheduled_post(post_id: str, data: dict) -> bool:
    db = await get_db()
    try:
        sets = ", ".join([f"{k} = ?" for k in data.keys()])
        await db.execute(
            f"UPDATE scheduled_posts SET {sets} WHERE id = ?",
            list(data.values()) + [post_id]
        )
        await db.commit()
        return True
    finally:
        await db.close()


async def delete_scheduled_post(post_id: str) -> bool:
    db = await get_db()
    try:
        await db.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
        await db.commit()
        return True
    finally:
        await db.close()


async def get_pending_posts() -> list[dict]:
    """Get posts that are due for publishing."""
    now = datetime.utcnow().isoformat()
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT sp.*, v.processed_path, v.original_path, v.ai_description,
               fp.access_token, fp.page_id as fb_page_id, fp.page_name
               FROM scheduled_posts sp
               JOIN videos v ON sp.video_id = v.id
               JOIN fb_pages fp ON sp.page_id = fp.id
               WHERE sp.status = 'pending' AND sp.scheduled_time <= ?
               ORDER BY sp.scheduled_time""",
            (now,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()


# ─── App Settings ───

async def get_setting(key: str, default: str = "") -> str:
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        return row["value"] if row else default
    finally:
        await db.close()


async def set_setting(key: str, value: str):
    db = await get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, datetime.utcnow().isoformat())
        )
        await db.commit()
    finally:
        await db.close()


# ─── Statistics ───

async def get_stats() -> dict:
    db = await get_db()
    try:
        stats = {}
        # Video counts
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM videos")
        row = await cursor.fetchone()
        stats["total_videos"] = row["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM videos WHERE status = 'downloaded'")
        row = await cursor.fetchone()
        stats["downloaded"] = row["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM videos WHERE status = 'processed'")
        row = await cursor.fetchone()
        stats["processed"] = row["cnt"]

        cursor = await db.execute("SELECT COUNT(*) as cnt FROM videos WHERE status = 'published'")
        row = await cursor.fetchone()
        stats["published"] = row["cnt"]

        # Page count
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM fb_pages WHERE is_active = 1")
        row = await cursor.fetchone()
        stats["active_pages"] = row["cnt"]

        # Scheduled posts
        cursor = await db.execute("SELECT COUNT(*) as cnt FROM scheduled_posts WHERE status = 'pending'")
        row = await cursor.fetchone()
        stats["pending_posts"] = row["cnt"]

        return stats
    finally:
        await db.close()
