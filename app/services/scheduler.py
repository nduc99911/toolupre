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

            # Build caption
            caption = post.get("caption", "")
            hashtags = post.get("hashtags", "")
            if hashtags:
                caption = f"{caption}\n\n{hashtags}"

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
