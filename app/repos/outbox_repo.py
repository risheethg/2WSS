"""
Outbox Events Repository

Repository for managing outbox events for reliable message publishing.
"""

from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta

from app.models.outbox import OutboxEvent, OutboxEventCreate, OutboxEventInDB
from app.core.logger import logger


class OutboxRepository:
    """Repository for outbox events"""

    def create_event(self, db: Session, event_data: OutboxEventCreate) -> OutboxEventInDB:
        """Create a new outbox event"""
        db_event = OutboxEvent(
            event_type=event_data.event_type,
            entity_type=event_data.entity_type,
            entity_id=event_data.entity_id,
            payload=event_data.to_json_payload()
        )
        db.add(db_event)
        db.flush()  # Get the ID without committing
        return OutboxEventInDB.from_orm(db_event)

    def get_unprocessed_events(self, db: Session, limit: int = 100) -> List[OutboxEventInDB]:
        """Get unprocessed events for publishing"""
        events = db.query(OutboxEvent).filter(
            OutboxEvent.is_processed == False
        ).order_by(OutboxEvent.created_at).limit(limit).all()
        
        return [OutboxEventInDB.from_orm(event) for event in events]

    def mark_as_processed(self, db: Session, event_id: int) -> bool:
        """Mark event as successfully processed"""
        event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
        if event:
            event.is_processed = True
            event.processed_at = datetime.utcnow()
            db.commit()
            return True
        return False

    def increment_retry_count(self, db: Session, event_id: int, error_message: str = None) -> bool:
        """Increment retry count and log error"""
        event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
        if event:
            event.retry_count += 1
            event.last_error = error_message
            db.commit()
            return True
        return False

    def get_failed_events(self, db: Session, max_retries: int = 5) -> List[OutboxEventInDB]:
        """Get events that have exceeded max retry count (for dead letter processing)"""
        events = db.query(OutboxEvent).filter(
            OutboxEvent.is_processed == False,
            OutboxEvent.retry_count >= max_retries
        ).all()
        
        return [OutboxEventInDB.from_orm(event) for event in events]

    def delete_old_processed_events(self, db: Session, days_old: int = 30) -> int:
        """Clean up old processed events"""
        cutoff_date = datetime.utcnow() - timedelta(days=days_old)
        deleted_count = db.query(OutboxEvent).filter(
            OutboxEvent.is_processed == True,
            OutboxEvent.processed_at < cutoff_date
        ).delete()
        db.commit()
        return deleted_count


# Global repository instance
outbox_repo = OutboxRepository()