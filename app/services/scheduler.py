"""
ReupMaster Pro - Task Scheduler Service
Handles scheduled posting using APScheduler.
"""
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app import database as db
from app.services.facebook_api import FacebookAPI
from app.config import settings
import os

logger = logging.getLogger("reupmaster.scheduler")


class PostScheduler:
    """Scheduler for automatic post publishing."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._running = False

    def start(self):
        """Start the scheduler."""
        if not self._running:
            # Check for pending posts every 60 seconds
            self.scheduler.add_job(
                self._check_pending_posts,
                trigger=IntervalTrigger(seconds=60),
                id="check_pending_posts",
                name="Check and publish pending posts",
                replace_existing=True,
            )
            # Check for pending seeding tasks every 45 seconds
            self.scheduler.add_job(
                self._check_seeding_tasks,
                trigger=IntervalTrigger(seconds=45),
                id="check_seeding_tasks",
                name="Execute pending seeding tasks",
                replace_existing=True,
            )
            # Reset daily seeding limits at midnight
            self.scheduler.add_job(
                self._reset_daily_limits,
                trigger=IntervalTrigger(hours=24),
                id="reset_seeding_limits",
                name="Reset daily seeding limits",
                replace_existing=True,
            )
            # Check for Auto Campaigns every hour
            self.scheduler.add_job(
                self._run_auto_campaigns,
                trigger=IntervalTrigger(minutes=60),
                id="run_auto_campaigns",
                name="Scan and execute auto campaigns",
                replace_existing=True,
            )
            self.scheduler.start()
            self._running = True
            logger.info("Post scheduler started (with seeding)")

    def stop(self):
        """Stop the scheduler."""
        if self._running:
            self.scheduler.shutdown(wait=False)
            self._running = False
            logger.info("Post scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    async def _check_pending_posts(self):
        """Check for and publish any pending posts that are due."""
        try:
            pending = await db.get_pending_posts()
            if not pending:
                return

            logger.info(f"Found {len(pending)} pending posts to publish")

            for post in pending:
                await self._publish_post(post)

        except Exception as e:
            logger.error(f"Error checking pending posts: {e}")

    async def _publish_post(self, post: dict):
        """Publish a single scheduled post."""
        post_id = post["id"]
        try:
            # Get the video path (prefer processed over original)
            video_path = post.get("processed_path") or post.get("original_path")
            if not video_path:
                await db.update_scheduled_post(post_id, {
                    "status": "failed",
                    "error_message": "No video file found"
                })
                return

            # Mark as processing immediately to prevent duplicate posting
            await db.update_scheduled_post(post_id, {"status": "processing"})


            # Build caption
            caption = post.get("caption", "")
            hashtags = post.get("hashtags", "")
            if hashtags:
                caption = f"{caption}\n\n{hashtags}"

            is_image = "Bộ ảnh" in post.get("video_title", "") or (post.get("thumbnail_path") and not post.get("original_path", "").endswith(".mp4") and os.path.isdir(video_path))

            if is_image:
                images = []
                if os.path.isdir(video_path):
                    valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
                    for f in sorted(os.listdir(video_path)):
                        if os.path.splitext(f)[1].lower() in valid_exts:
                            images.append(os.path.join(video_path, f))
                            
                if post["fb_page_id"].startswith("tele:"):
                    chat_id = post["fb_page_id"].replace("tele:", "")
                    from app.services.telegram_bot import bot
                    from aiogram.types import FSInputFile
                    if not bot: raise Exception("Telegram bot token not configured")
                    for img in images:
                        await bot.send_photo(chat_id, FSInputFile(img), caption=caption)
                    result = {"success": True, "post_id": f"tele_{post_id}"}
                else:
                    result = await FacebookAPI.post_images(
                        page_id=post["fb_page_id"],
                        access_token=post["access_token"],
                        image_paths=images,
                        caption=caption,
                    )
            else:
                if post["fb_page_id"].startswith("tele:"):
                    chat_id = post["fb_page_id"].replace("tele:", "")
                    from app.services.telegram_bot import bot
                    from aiogram.types import FSInputFile
                    if not bot: raise Exception("Telegram bot token not configured")
                    await bot.send_video(chat_id, FSInputFile(video_path), caption=caption)
                    result = {"success": True, "post_id": f"tele_{post_id}"}
                else:
                    # Publish to Facebook
                    result = await FacebookAPI.post_video(
                        page_id=post["fb_page_id"],
                        access_token=post["access_token"],
                        video_path=video_path,
                        caption=caption,
                        title=post.get("video_title", ""),
                    )

            if result.get("success"):
                await db.update_scheduled_post(post_id, {
                    "status": "published",
                    "fb_post_id": result.get("post_id", ""),
                    "published_at": datetime.utcnow().isoformat(),
                })
                # Also update video status
                await db.update_video(post["video_id"], {"status": "published"})
                logger.info(f"Post {post_id} published successfully")

                # Auto cleanup if enabled
                if settings.AUTO_CLEANUP_VIDEO:
                    await self._cleanup_video_files(post["video_id"])
            else:
                error = result.get("error", "Unknown error")
                await db.update_scheduled_post(post_id, {
                    "status": "failed",
                    "error_message": error,
                })
                logger.error(f"Failed to publish post {post_id}: {error}")

        except Exception as e:
            await db.update_scheduled_post(post_id, {
                "status": "failed",
                "error_message": str(e),
            })
            logger.error(f"Exception publishing post {post_id}: {e}")

    async def _cleanup_video_files(self, video_id: str):
        """Delete physical video files to save space."""
        try:
            video = await db.get_video(video_id)
            if not video:
                return

            files_to_delete = [video.get("original_path"), video.get("processed_path"), video.get("thumbnail_path")]
            for path in files_to_delete:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                        logger.info(f"Deleted file: {path}")
                    except Exception as fe:
                        logger.error(f"Error deleting file {path}: {fe}")

            # Update database to reflect files are gone
            await db.update_video(video_id, {
                "original_path": "",
                "processed_path": "",
                "thumbnail_path": ""
            })
            logger.info(f"Cleanup completed for video {video_id}")
        except Exception as e:
            logger.error(f"Error during video cleanup: {e}")

    async def _check_seeding_tasks(self):
        """Check and execute pending seeding tasks."""
        try:
            from app.services.seeding_service import run_pending_seeding_tasks
            await run_pending_seeding_tasks()
        except Exception as e:
            logger.error(f"Error running seeding tasks: {e}")

    async def _reset_daily_limits(self):
        """Reset daily action limits for seeding accounts."""
        try:
            adb = await db.get_db()
            await adb.execute("UPDATE seeding_accounts SET actions_today = 0")
            await adb.commit()
            await adb.close()
            logger.info("Daily seeding limits reset")
        except Exception as e:
            logger.error(f"Error resetting daily limits: {e}")

    async def _run_auto_campaigns(self):
        """Scan target URLs for new videos, download, process, and schedule."""
        from datetime import datetime, timedelta
        import uuid
        import json
        from app.services.douyin_api import DouyinAPI
        import asyncio
        
        try:
            campaigns = await db.get_active_campaigns()
            current_hour = datetime.now().hour
            
            for camp in campaigns:
                if int(camp.get('scan_hour', 0)) != current_hour:
                    continue
                    
                logger.info(f"Running auto campaign: {camp['name']}")
                
                try:
                    videos = await DouyinAPI.get_profile_videos(camp['target_url'], limit=5)
                except Exception as e:
                    logger.error(f"Failed to fetch douyin profile for campaign {camp['name']}: {e}")
                    continue
                
                if not videos:
                    continue
                    
                adb = await db.get_db()
                for v in videos:
                    cursor = await adb.execute("SELECT id FROM videos WHERE source_url = ?", (v['url'],))
                    existing = await cursor.fetchone()
                    if existing:
                        continue 
                        
                    logger.info(f"New video found for campaign {camp['name']}: {v['url']}")
                    
                    video_id = str(uuid.uuid4())[:8]
                    await db.create_video({
                        "id": video_id,
                        "source_url": v['url'],
                        "source_platform": "douyin",
                        "title": v.get('desc', ''),
                        "status": "pending",
                        "processing_options": camp.get('processing_options', '{}')
                    })
                    
                    asyncio.create_task(self._auto_campaign_pipeline(video_id, camp))
                    
                await adb.close()
        except Exception as e:
            logger.error(f"Error in auto campaigns: {e}")

    async def _auto_campaign_pipeline(self, video_id: str, camp: dict):
        from app.main import _download_task
        from app.services.video_processor import VideoProcessor
        from datetime import datetime, timedelta
        import asyncio
        import json
        
        try:
            logger.info(f"Starting auto pipeline for video {video_id}")
            video = await db.get_video(video_id)
            if not video: return
            
            await _download_task(video['source_url'], video_id)
            
            video = await db.get_video(video_id)
            if video.get('status') != 'downloaded':
                return
                
            opts = json.loads(camp.get('processing_options', '{}'))
            if opts:
                processor = VideoProcessor(video_id, opts)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, processor.process)
                
            video = await db.get_video(video_id)
            if video.get('status') in ['processed', 'downloaded']:
                now = datetime.now()
                post_time = now.replace(hour=int(camp.get('post_hour', 12)), minute=0, second=0)
                if post_time <= now:
                    post_time += timedelta(days=1)
                    
                await self.add_scheduled_post(
                    video_id=video_id,
                    page_id=camp.get('page_id'),
                    scheduled_time=post_time.strftime("%Y-%m-%dT%H:%M"),
                    caption=video.get('title', '')
                )
                logger.info(f"Auto pipeline completed! Video {video_id} scheduled for {post_time}")
        except Exception as e:
            logger.error(f"Error in auto pipeline for {video_id}: {e}")

    async def add_scheduled_post(self, video_id: str, page_id: str,
                                  scheduled_time: str, caption: str = "",
                                  hashtags: str = "") -> dict:
        """Add a new scheduled post."""
        import uuid
        post_id = str(uuid.uuid4())[:8]

        post_data = {
            "id": post_id,
            "video_id": video_id,
            "page_id": page_id,
            "scheduled_time": scheduled_time,
            "caption": caption,
            "hashtags": hashtags,
            "status": "pending",
        }

        await db.create_scheduled_post(post_data)
        return post_data

    async def cancel_post(self, post_id: str) -> bool:
        """Cancel a scheduled post."""
        return await db.delete_scheduled_post(post_id)

    def get_status(self) -> dict:
        """Get scheduler status."""
        jobs = []
        if self._running:
            for job in self.scheduler.get_jobs():
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                })

        return {
            "running": self._running,
            "jobs": jobs,
        }


# Global scheduler instance
post_scheduler = PostScheduler()
