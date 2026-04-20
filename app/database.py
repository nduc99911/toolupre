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

CREATE TABLE IF NOT EXISTS seeding_accounts (
    id TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    fb_user_id TEXT DEFAULT '',
    access_token TEXT NOT NULL,
    account_type TEXT DEFAULT 'clone',
    status TEXT DEFAULT 'active',
    daily_limit INTEGER DEFAULT 50,
    actions_today INTEGER DEFAULT 0,
    last_action_at TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seeding_tasks (
    id TEXT PRIMARY KEY,
    post_id TEXT DEFAULT '',
    fb_post_id TEXT DEFAULT '',
    page_name TEXT DEFAULT '',
    account_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    comment_text TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    scheduled_at TEXT DEFAULT '',
    executed_at TEXT DEFAULT '',
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES seeding_accounts(id)
);

CREATE TABLE IF NOT EXISTS fb_page_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_db_id TEXT NOT NULL,
    fan_count INTEGER DEFAULT 0,
    followers_count INTEGER DEFAULT 0,
    total_engagement INTEGER DEFAULT 0,
    avg_engagement REAL DEFAULT 0,
    post_count_recent INTEGER DEFAULT 0,
    captured_at TEXT NOT NULL,
    FOREIGN KEY (page_db_id) REFERENCES fb_pages(id)
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
        # Check if page_id already exists to preserve its internal `id`
        cursor = await db.execute("SELECT id FROM fb_pages WHERE page_id = ?", (page_data.get("page_id"),))
        existing = await cursor.fetchone()

        if existing:
            # Preserve old `id`
            old_id = existing[0]
            page_data["id"] = old_id
            
            # Update
            cols_to_update = [k for k in page_data.keys() if k != "id"]
            sets = ", ".join([f"{k} = ?" for k in cols_to_update])
            values = [page_data[k] for k in cols_to_update] + [old_id]
            
            await db.execute(f"UPDATE fb_pages SET {sets} WHERE id = ?", values)
        else:
            cols = ", ".join(page_data.keys())
            placeholders = ", ".join(["?" for _ in page_data])
            await db.execute(
                f"INSERT INTO fb_pages ({cols}) VALUES ({placeholders})",
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
    now = datetime.now().isoformat()
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


async def get_dashboard_analytics() -> dict:
    """Get detailed analytics for dashboard charts (SO9-style)."""
    db = await get_db()
    try:
        analytics = {}

        # Videos by date (last 7 days)
        cursor = await db.execute("""
            SELECT DATE(created_at) as date, COUNT(*) as count, status 
            FROM videos 
            WHERE created_at >= DATE('now', '-7 days')
            GROUP BY DATE(created_at), status
            ORDER BY date
        """)
        rows = await cursor.fetchall()
        daily = {}
        for row in rows:
            d = dict(row)
            date = d["date"]
            if date not in daily:
                daily[date] = {"date": date, "downloaded": 0, "processed": 0, "published": 0, "failed": 0}
            status = d.get("status", "")
            if status in daily[date]:
                daily[date][status] = d["count"]
        analytics["daily_stats"] = list(daily.values())

        # Videos by platform
        cursor = await db.execute("""
            SELECT source_platform, COUNT(*) as count 
            FROM videos 
            GROUP BY source_platform
        """)
        rows = await cursor.fetchall()
        analytics["by_platform"] = [dict(r) for r in rows]

        # Videos by status
        cursor = await db.execute("""
            SELECT status, COUNT(*) as count 
            FROM videos 
            GROUP BY status
        """)
        rows = await cursor.fetchall()
        analytics["by_status"] = [dict(r) for r in rows]

        # Pages with post counts
        cursor = await db.execute("""
            SELECT fp.page_name, fp.page_id, COUNT(sp.id) as post_count,
                   SUM(CASE WHEN sp.status = 'published' THEN 1 ELSE 0 END) as published_count,
                   SUM(CASE WHEN sp.status = 'pending' THEN 1 ELSE 0 END) as pending_count
            FROM fb_pages fp
            LEFT JOIN scheduled_posts sp ON fp.id = sp.page_id
            WHERE fp.is_active = 1
            GROUP BY fp.id
            ORDER BY post_count DESC
        """)
        rows = await cursor.fetchall()
        analytics["page_stats"] = [dict(r) for r in rows]

        # Recent activity (last 20 actions)
        cursor = await db.execute("""
            SELECT id, title, status, source_platform, updated_at 
            FROM videos 
            ORDER BY updated_at DESC 
            LIMIT 20
        """)
        rows = await cursor.fetchall()
        analytics["recent_activity"] = [dict(r) for r in rows]

        # Total storage used
        cursor = await db.execute("""
            SELECT SUM(file_size) as total_size FROM videos
        """)
        row = await cursor.fetchone()
        analytics["total_storage"] = dict(row)["total_size"] or 0

        return analytics
    finally:
        await db.close()


async def save_page_stats(stats_data: dict) -> bool:
    """Save daily snapshot of page statistics."""
    db = await get_db()
    try:
        now = datetime.utcnow().isoformat()
        await db.execute("""
            INSERT INTO fb_page_stats (
                page_db_id, fan_count, followers_count, total_engagement, 
                avg_engagement, post_count_recent, captured_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            stats_data["page_db_id"], stats_data.get("fan_count", 0),
            stats_data.get("followers_count", 0), stats_data.get("total_engagement", 0),
            stats_data.get("avg_engagement", 0), stats_data.get("post_count_recent", 0),
            now
        ))
        await db.commit()
        return True
    finally:
        await db.close()


async def get_page_stats_history(page_db_id: str, days: int = 30) -> list[dict]:
    """Get history of stats for a page to draw charts."""
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT * FROM fb_page_stats 
            WHERE page_db_id = ? 
            AND captured_at >= DATE('now', ?)
            ORDER BY captured_at ASC
        """, (page_db_id, f"-{days} days"))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()

