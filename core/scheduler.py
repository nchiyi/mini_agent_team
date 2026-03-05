"""
Scheduler — Cron-based task scheduling using APScheduler.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class Scheduler:
    """Manages scheduled tasks for skills."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._notify_callback = None

    def set_notify_callback(self, callback):
        """Set callback for sending messages to Telegram."""
        self._notify_callback = callback

    def add_cron_job(self, name: str, cron_expr: str, func):
        """
        Add a cron-scheduled job.

        Args:
            name: Unique job name
            cron_expr: Cron expression (e.g., '0 9 * * *' for 9 AM daily)
            func: Async function to execute
        """
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            logger.error(f"Invalid cron expression for {name}: {cron_expr}")
            return

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4],
        )

        self.scheduler.add_job(func, trigger, id=name, replace_existing=True)
        logger.info(f"Scheduled job '{name}' with cron: {cron_expr}")

    def start(self):
        """Start the scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")

    def stop(self):
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    async def notify(self, user_id: int, message: str):
        """Send a notification to a user via Telegram."""
        if self._notify_callback:
            await self._notify_callback(user_id, message)
