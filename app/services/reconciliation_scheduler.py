import asyncio
import logging
from datetime import datetime, time
from typing import Optional
from app.services.reconciliation_service import ReconciliationService
from app.core.database import SessionLocal
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ReconciliationScheduler:
    def __init__(self):
        self.settings = get_settings()
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
    
    async def start_scheduler(self):
        """Start the reconciliation scheduler."""
        if self.is_running:
            logger.warning("Reconciliation scheduler is already running")
            return
        
        self.is_running = True
        self.task = asyncio.create_task(self._schedule_loop())
        logger.info("Reconciliation scheduler started")
    
    async def stop_scheduler(self):
        """Stop the reconciliation scheduler."""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Reconciliation scheduler stopped")
    
    async def _schedule_loop(self):
        """Main scheduling loop."""
        while self.is_running:
            try:
                # Check if it's time to run reconciliation
                now = datetime.now()
                run_time = time(
                    hour=getattr(self.settings, 'RECONCILIATION_HOUR', 2),  # Default 2 AM
                    minute=getattr(self.settings, 'RECONCILIATION_MINUTE', 0)  # Default :00
                )
                
                target_datetime = datetime.combine(now.date(), run_time)
                
                # If target time has passed today, schedule for tomorrow
                if now > target_datetime:
                    target_datetime = target_datetime.replace(day=target_datetime.day + 1)
                
                # For frequent testing: run every 10 minutes
                # Comment out for daily schedule, uncomment for testing
                # seconds_until_run = 600  # 10 minutes
                
                # Original daily schedule:
                # Calculate seconds until next run
                seconds_until_run = (target_datetime - now).total_seconds()
                
                logger.info(f"Next reconciliation scheduled for {target_datetime}")
                
                # Wait until it's time to run
                await asyncio.sleep(seconds_until_run)
                
                if self.is_running:  # Check if we weren't cancelled during sleep
                    await self._run_reconciliation()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in reconciliation scheduler: {str(e)}")
                # Wait 1 hour before retrying on error
                await asyncio.sleep(3600)
    
    async def _run_reconciliation(self):
        """Execute the reconciliation process."""
        logger.info("Starting scheduled reconciliation")
        
        try:
            with SessionLocal() as db:
                reconciliation_service = ReconciliationService(db)
                
                # Run reconciliation with auto-resolve for simple cases
                auto_resolve = getattr(self.settings, 'RECONCILIATION_AUTO_RESOLVE', True)
                report = await reconciliation_service.run_reconciliation(auto_resolve=auto_resolve)
                
                logger.info(
                    f"Scheduled reconciliation completed: Report ID {report.id}, "
                    f"{report.mismatches_found} mismatches, "
                    f"{report.auto_resolved} auto-resolved, "
                    f"{report.manual_review_needed} need manual review"
                )
        
        except Exception as e:
            logger.error(f"Scheduled reconciliation failed: {str(e)}")
    
    async def run_manual_reconciliation(self, auto_resolve: bool = False) -> dict:
        """Run reconciliation manually (for admin endpoints)."""
        logger.info("Starting manual reconciliation")
        
        try:
            with SessionLocal() as db:
                reconciliation_service = ReconciliationService(db)
                report = await reconciliation_service.run_reconciliation(auto_resolve=auto_resolve)
                
                return {
                    "success": True,
                    "report_id": report.id,
                    "mismatches_found": report.mismatches_found,
                    "auto_resolved": report.auto_resolved,
                    "manual_review_needed": report.manual_review_needed,
                    "status": report.status
                }
        
        except Exception as e:
            logger.error(f"Manual reconciliation failed: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }


# Global scheduler instance
_scheduler: Optional[ReconciliationScheduler] = None


async def get_scheduler() -> ReconciliationScheduler:
    """Get the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = ReconciliationScheduler()
    return _scheduler


async def start_reconciliation_scheduler():
    """Start the reconciliation scheduler (called during app startup)."""
    scheduler = await get_scheduler()
    await scheduler.start_scheduler()


async def stop_reconciliation_scheduler():
    """Stop the reconciliation scheduler (called during app shutdown)."""
    global _scheduler
    if _scheduler:
        await _scheduler.stop_scheduler()