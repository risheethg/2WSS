"""
Admin Routes for Outbox Management

Routes for monitoring and managing the outbox system.
"""

from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Dict, Any

from app.core.database import get_db, SessionLocal
from app.core.response import response_handler
from app.repos.outbox_repo import outbox_repo
from app.services.outbox_processor import outbox_processor

router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)


@router.get("/outbox/status")
def get_outbox_status(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get outbox processing status and statistics"""
    try:
        # Get unprocessed events
        unprocessed_events = outbox_repo.get_unprocessed_events(db, limit=1000)
        unprocessed_count = len(unprocessed_events)
        
        # Get failed events
        failed_events = outbox_repo.get_failed_events(db)
        failed_count = len(failed_events)
        
        status = {
            "unprocessed_events": unprocessed_count,
            "failed_events": failed_count,
            "processor_running": outbox_processor.running
        }
        
        return response_handler.success(data=status)
        
    except Exception as e:
        return response_handler.failure(f"Error getting outbox status: {e}", 500)


@router.post("/outbox/process-failed")
def process_failed_events(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Manually process failed outbox events"""
    try:
        def process_failed():
            with SessionLocal() as db_session:
                dlq_count = outbox_processor.process_failed_events(db_session)
                return dlq_count
        
        background_tasks.add_task(process_failed)
        
        return response_handler.success(
            message="Started processing failed outbox events in background"
        )
        
    except Exception as e:
        return response_handler.failure(f"Error processing failed events: {e}", 500)


@router.post("/outbox/cleanup")
def cleanup_old_events(days_old: int = 30, db: Session = Depends(get_db)):
    """Clean up old processed outbox events"""
    try:
        deleted_count = outbox_processor.cleanup_old_events(db, days_old)
        
        return response_handler.success(
            data={"deleted_count": deleted_count},
            message=f"Cleaned up {deleted_count} old outbox events"
        )
        
    except Exception as e:
        return response_handler.failure(f"Error cleaning up events: {e}", 500)


@router.get("/outbox/events/unprocessed")
def get_unprocessed_events(limit: int = 50, db: Session = Depends(get_db)):
    """Get list of unprocessed outbox events for debugging"""
    try:
        events = outbox_repo.get_unprocessed_events(db, limit)
        
        event_data = [{
            "id": event.id,
            "event_type": event.event_type,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "created_at": event.created_at.isoformat(),
            "retry_count": event.retry_count,
            "last_error": event.last_error
        } for event in events]
        
        return response_handler.success(data=event_data)
        
    except Exception as e:
        return response_handler.failure(f"Error getting unprocessed events: {e}", 500)


@router.get("/outbox/events/failed")
def get_failed_events(db: Session = Depends(get_db)):
    """Get list of failed outbox events for debugging"""
    try:
        events = outbox_repo.get_failed_events(db)
        
        event_data = [{
            "id": event.id,
            "event_type": event.event_type,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "created_at": event.created_at.isoformat(),
            "retry_count": event.retry_count,
            "last_error": event.last_error
        } for event in events]
        
        return response_handler.success(data=event_data)
        
    except Exception as e:
        return response_handler.failure(f"Error getting failed events: {e}", 500)