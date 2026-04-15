"""
ReupMaster Pro - Auto Seeding Service
Automatically Like, Comment, Share posts using clone/via accounts.
Mimics real user behavior with random delays to avoid detection.
"""
import asyncio
import random
import uuid
import logging
import httpx
from datetime import datetime, timedelta
from app.config import settings

logger = logging.getLogger("reupmaster.seeding")

# ─── Predefined Vietnamese comments for seeding ───
SEEDING_COMMENTS = {
    "praise": [
        "Hay quá! 🔥🔥🔥",
        "Content chất lượng luôn 👍",
        "Quá đỉnh! Chia sẻ ngay cho bạn bè 💯",
        "Video này xịn thật sự ❤️",
        "Cảm ơn bạn đã chia sẻ! 🙏",
        "Nội dung rất bổ ích 👏👏",
        "Tuyệt vời! Follow ngay 🥰",
        "Xem mãi không chán luôn 😍",
        "Phải save lại video này 📌",
        "Đỉnh của chóp 🏆",
        "Mình rất thích nội dung này 💕",
        "Chia sẻ cho mọi người cùng xem nhé!",
        "Quá tâm huyết, respect! 🫡",
        "Hay lắm, làm thêm content kiểu này đi ạ 🙌",
        "Video chất lượng, đã follow rồi! ✅",
    ],
    "question": [
        "Cho mình hỏi thêm thông tin được không ạ? 🤔",
        "Mình có thể mua ở đâu vậy? 🛒",
        "Giá bao nhiêu vậy bạn? 💰",
        "Có ship toàn quốc không ạ? 🚚",
        "Inbox mình giá nhé! 📩",
        "Cho mình xin link sản phẩm với ạ 🔗",
        "Có khuyến mãi gì không bạn? 🏷️",
        "Mình muốn đặt mua, liên hệ sao ạ? 📱",
        "Sản phẩm này dùng có tốt không bạn?",
        "Bao lâu thì nhận được hàng? ⏰",
    ],
    "engage": [
        "Tag bạn bè vào đây nè @friends 👀",
        "Ai đồng ý thì like đi nào! 👍",
        "Share cho bạn bè cùng biết nhé!",
        "Mình vừa share rồi đó 📲",
        "Đã like + follow! Mong nội dung mới 🌟",
        "Admin ơi làm thêm nhiều video thế này nha 🎬",
        "Nội dung mình cần tìm bấy lâu nay 💎",
    ],
}


def get_random_comments(count: int = 3, style: str = "mixed") -> list[str]:
    """Get random seeding comments."""
    if style == "mixed":
        all_comments = []
        for category in SEEDING_COMMENTS.values():
            all_comments.extend(category)
    elif style in SEEDING_COMMENTS:
        all_comments = SEEDING_COMMENTS[style]
    else:
        all_comments = SEEDING_COMMENTS["praise"]
    
    return random.sample(all_comments, min(count, len(all_comments)))


async def execute_like(fb_post_id: str, access_token: str) -> dict:
    """Like a Facebook post using Graph API."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v19.0/{fb_post_id}/likes",
                params={"access_token": access_token}
            )
            data = resp.json()
            
            if resp.status_code == 200 and data.get("success"):
                logger.info(f"✅ Liked post {fb_post_id}")
                return {"success": True, "action": "like"}
            else:
                error = data.get("error", {}).get("message", "Unknown error")
                logger.warning(f"❌ Like failed: {error}")
                return {"success": False, "error": error}
    except Exception as e:
        logger.error(f"Like exception: {e}")
        return {"success": False, "error": str(e)}


async def execute_comment(fb_post_id: str, access_token: str, comment_text: str) -> dict:
    """Comment on a Facebook post using Graph API."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v19.0/{fb_post_id}/comments",
                params={"access_token": access_token},
                data={"message": comment_text}
            )
            data = resp.json()
            
            if resp.status_code == 200 and data.get("id"):
                logger.info(f"✅ Commented on post {fb_post_id}: {comment_text[:30]}...")
                return {"success": True, "action": "comment", "comment_id": data["id"]}
            else:
                error = data.get("error", {}).get("message", "Unknown error")
                logger.warning(f"❌ Comment failed: {error}")
                return {"success": False, "error": error}
    except Exception as e:
        logger.error(f"Comment exception: {e}")
        return {"success": False, "error": str(e)}


async def execute_share(fb_post_id: str, access_token: str) -> dict:
    """Share a Facebook post to user's feed using Graph API."""
    try:
        post_link = f"https://www.facebook.com/{fb_post_id}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://graph.facebook.com/v19.0/me/feed",
                params={"access_token": access_token},
                data={"link": post_link}
            )
            data = resp.json()
            
            if resp.status_code == 200 and data.get("id"):
                logger.info(f"✅ Shared post {fb_post_id}")
                return {"success": True, "action": "share", "share_id": data["id"]}
            else:
                error = data.get("error", {}).get("message", "Unknown error")
                logger.warning(f"❌ Share failed: {error}")
                return {"success": False, "error": error}
    except Exception as e:
        logger.error(f"Share exception: {e}")
        return {"success": False, "error": str(e)}


async def execute_seeding_task(task: dict) -> dict:
    """Execute a single seeding task (like/comment/share)."""
    action = task["action_type"]
    token = task["access_token"]
    fb_post_id = task["fb_post_id"]
    
    if action == "like":
        return await execute_like(fb_post_id, token)
    elif action == "comment":
        return await execute_comment(fb_post_id, token, task.get("comment_text", "👍"))
    elif action == "share":
        return await execute_share(fb_post_id, token)
    else:
        return {"success": False, "error": f"Unknown action: {action}"}


async def create_seeding_plan(
    fb_post_id: str,
    page_name: str,
    accounts: list[dict],
    actions: dict,
    delay_range: tuple = (30, 180),
) -> list[dict]:
    """
    Create a seeding plan with staggered timing.
    
    Args:
        fb_post_id: The Facebook post ID to seed
        page_name: Name of the page (for display)
        accounts: List of seeding accounts
        actions: Dict of actions to perform, e.g. {"like": True, "comment": True, "share": False}
        delay_range: Min/max seconds between actions (random delay)
    
    Returns list of task dicts ready to be saved to DB.
    """
    tasks = []
    base_time = datetime.utcnow()
    current_delay = 0
    
    # Shuffle accounts for randomness
    shuffled = list(accounts)
    random.shuffle(shuffled)
    
    comment_pool = get_random_comments(len(shuffled) * 2, "mixed")
    comment_idx = 0
    
    for account in shuffled:
        # Check daily limit
        if account.get("actions_today", 0) >= account.get("daily_limit", 50):
            logger.info(f"Account {account['name']} reached daily limit, skipping")
            continue
        
        # Add random delay between accounts
        current_delay += random.randint(delay_range[0], delay_range[1])
        scheduled_time = base_time + timedelta(seconds=current_delay)
        
        # Like action
        if actions.get("like", True):
            tasks.append({
                "id": str(uuid.uuid4())[:8],
                "fb_post_id": fb_post_id,
                "page_name": page_name,
                "account_id": account["id"],
                "account_name": account["name"],
                "action_type": "like",
                "comment_text": "",
                "status": "pending",
                "scheduled_at": scheduled_time.isoformat(),
                "created_at": datetime.utcnow().isoformat(),
            })
            current_delay += random.randint(5, 30)
        
        # Comment action
        if actions.get("comment", True):
            comment = comment_pool[comment_idx % len(comment_pool)] if comment_pool else "👍"
            comment_idx += 1
            
            tasks.append({
                "id": str(uuid.uuid4())[:8],
                "fb_post_id": fb_post_id,
                "page_name": page_name,
                "account_id": account["id"],
                "account_name": account["name"],
                "action_type": "comment",
                "comment_text": comment,
                "status": "pending",
                "scheduled_at": (base_time + timedelta(seconds=current_delay)).isoformat(),
                "created_at": datetime.utcnow().isoformat(),
            })
            current_delay += random.randint(10, 45)
        
        # Share action (less frequent)
        if actions.get("share", False):
            tasks.append({
                "id": str(uuid.uuid4())[:8],
                "fb_post_id": fb_post_id,
                "page_name": page_name,
                "account_id": account["id"],
                "account_name": account["name"],
                "action_type": "share",
                "comment_text": "",
                "status": "pending",
                "scheduled_at": (base_time + timedelta(seconds=current_delay)).isoformat(),
                "created_at": datetime.utcnow().isoformat(),
            })
            current_delay += random.randint(30, 120)
    
    logger.info(f"Created seeding plan: {len(tasks)} tasks for post {fb_post_id}")
    return tasks


async def run_pending_seeding_tasks():
    """Check and execute pending seeding tasks that are due.
    Called periodically by the scheduler."""
    import aiosqlite
    from app.config import settings
    
    now = datetime.utcnow().isoformat()
    
    try:
        db = await aiosqlite.connect(settings.DATABASE_URL)
        db.row_factory = aiosqlite.Row
        
        # Get pending tasks that are due
        cursor = await db.execute("""
            SELECT st.*, sa.access_token, sa.actions_today, sa.daily_limit
            FROM seeding_tasks st
            JOIN seeding_accounts sa ON st.account_id = sa.id
            WHERE st.status = 'pending' AND st.scheduled_at <= ?
            AND sa.status = 'active'
            ORDER BY st.scheduled_at
            LIMIT 5
        """, (now,))
        tasks = [dict(r) for r in await cursor.fetchall()]
        
        for task in tasks:
            # Check daily limit
            if task.get("actions_today", 0) >= task.get("daily_limit", 50):
                await db.execute(
                    "UPDATE seeding_tasks SET status = 'skipped', error_message = 'Daily limit reached' WHERE id = ?",
                    (task["id"],)
                )
                continue
            
            # Execute the action
            logger.info(f"🎯 Executing seeding: {task['action_type']} on {task['fb_post_id']} via account {task['account_id']}")
            result = await execute_seeding_task(task)
            
            if result.get("success"):
                await db.execute(
                    "UPDATE seeding_tasks SET status = 'completed', executed_at = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), task["id"])
                )
                # Increment actions_today
                await db.execute(
                    "UPDATE seeding_accounts SET actions_today = actions_today + 1, last_action_at = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), task["account_id"])
                )
            else:
                await db.execute(
                    "UPDATE seeding_tasks SET status = 'failed', error_message = ?, executed_at = ? WHERE id = ?",
                    (result.get("error", "Unknown"), datetime.utcnow().isoformat(), task["id"])
                )
            
            # Random delay between actions (2-8 seconds)
            await asyncio.sleep(random.uniform(2, 8))
        
        await db.commit()
        await db.close()
        
        if tasks:
            logger.info(f"Seeding round complete: {len(tasks)} tasks processed")
            
    except Exception as e:
        logger.error(f"Seeding scheduler error: {e}")
