import asyncio
import logging
from typing import List, Dict
from app import database as db
from app.services.video_processor import VideoProcessor

logger = logging.getLogger("reupmaster.queue")

class ProcessQueue:
    """Sequential processing queue for videos."""
    def __init__(self):
        self.queue = asyncio.Queue()
        self.worker_task = None
        self.current_video_id = None
        self.pending_ids = []

    def start(self):
        """Start the background worker if not already running."""
        if self.worker_task is None or self.worker_task.done():
            self.worker_task = asyncio.create_task(self._worker())
            logger.info("Sequential process queue worker started")

    async def add_videos(self, video_ids: List[str], options: Dict):
        """Add multiple videos to the queue."""
        for vid_id in video_ids:
            if vid_id not in self.pending_ids and vid_id != self.current_video_id:
                # Mark as processing (queued)
                await db.update_video(vid_id, {"status": "processing"})
                await self.queue.put((vid_id, options))
                self.pending_ids.append(vid_id)
        
        self.start()
        return len(video_ids)

    async def _worker(self):
        """Background worker that processes one video at a time."""
        while True:
            try:
                # Wait for a job
                video_id, options = await self.queue.get()
                self.current_video_id = video_id
                if video_id in self.pending_ids:
                    self.pending_ids.remove(video_id)

                logger.info(f"Queue: Starting processing for {video_id}")
                
                # Execute processing
                try:
                    await VideoProcessor.process_video(video_id, options)
                except Exception as e:
                    logger.error(f"Queue error processing {video_id}: {e}")
                    await db.update_video(video_id, {
                        "status": "failed",
                        "error_message": f"Queue worker error: {str(e)}"
                    })
                
                # Mark job as done in the queue tracking
                self.queue.task_done()
                self.current_video_id = None
                
                logger.info(f"Queue: Finished processing for {video_id}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Critical error in queue worker: {e}")
                await asyncio.sleep(5) # Cooldown on failure

    def get_status(self):
        """Get current queue status."""
        return {
            "current": self.current_video_id,
            "pending": self.pending_ids,
            "remaining_count": self.queue.qsize(),
            "is_running": self.worker_task is not None and not self.worker_task.done()
        }

# Global queue instance
process_queue = ProcessQueue()
