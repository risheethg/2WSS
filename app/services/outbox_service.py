"""
Outbox Service

This service manages the transactional outbox pattern operations:
- Creating outbox events within database transactions
- Managing event lifecycle (pending -> processing -> published/failed)
- Handling retries and dead letter queue logic
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.outbox import OutboxEvent, EventStatus
from app.core.config import settings

logger = logging.getLogger(__name__)

class OutboxService:
    """
    Service for managing transactional outbox events.
    """
    
    def __init__(self):
        self.default_max_retries = 5
        self.base_retry_delay = 2  # seconds
        self.max_retry_delay = 300  # 5 minutes
        
    def create_event(
        self,
        db: Session,
        event_type: str,
        aggregate_id: str,
        aggregate_type: str,
        payload: Dict[str, Any],
        topic: Optional[str] = None,
        partition_key: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        max_retries: Optional[int] = None
    ) -> OutboxEvent:
        """
        Create a new outbox event within the current database transaction.
        
        This method MUST be called within an active database transaction
        to ensure atomicity with the business operation.
        
        Args:
            db: Database session (must be in active transaction)
            event_type: Type of event (e.g., "customer_created")
            aggregate_id: ID of the aggregate (e.g., customer ID)
            aggregate_type: Type of aggregate (e.g., "customer")
            payload: Event payload data
            topic: Kafka topic (defaults to configured topic)
            partition_key: Kafka partition key (defaults to aggregate_id)
            metadata: Additional metadata
            max_retries: Maximum retry attempts
            
        Returns:
            OutboxEvent: Created outbox event
        """
        # Default values
        if topic is None:
            topic = settings.KAFKA_CUSTOMER_TOPIC
        if partition_key is None:
            partition_key = aggregate_id
        if max_retries is None:
            max_retries = self.default_max_retries
        
        # Create outbox event
        outbox_event = OutboxEvent(
            event_type=event_type,
            aggregate_id=str(aggregate_id),
            aggregate_type=aggregate_type,
            topic=topic,
            partition_key=partition_key,
            payload=payload,
            metadata=metadata or {},
            max_retries=max_retries,
            status=EventStatus.PENDING.value
        )
        
        db.add(outbox_event)
        db.flush()  # Get the ID without committing
        
        logger.debug(f"Created outbox event: {outbox_event.id} for {event_type}")
        
        return outbox_event
    
    def get_pending_events(
        self,
        db: Session,
        limit: int = 100,
        topic: Optional[str] = None
    ) -> List[OutboxEvent]:
        """
        Get pending events ready for processing.
        
        Args:
            db: Database session
            limit: Maximum number of events to retrieve
            topic: Filter by topic (optional)
            
        Returns:
            List of pending outbox events
        """
        query = db.query(OutboxEvent).filter(
            OutboxEvent.status == EventStatus.PENDING.value
        ).order_by(OutboxEvent.created_at)
        
        if topic:
            query = query.filter(OutboxEvent.topic == topic)
            
        return query.limit(limit).all()
    
    def get_retry_ready_events(
        self,
        db: Session,
        limit: int = 100
    ) -> List[OutboxEvent]:
        """
        Get events that are ready for retry.
        
        Args:
            db: Database session  
            limit: Maximum number of events to retrieve
            
        Returns:
            List of events ready for retry
        """
        now = datetime.utcnow()
        
        return db.query(OutboxEvent).filter(
            and_(
                OutboxEvent.status == EventStatus.FAILED.value,
                OutboxEvent.retry_count < OutboxEvent.max_retries,
                or_(
                    OutboxEvent.next_retry_at.is_(None),
                    OutboxEvent.next_retry_at <= now
                )
            )
        ).order_by(OutboxEvent.next_retry_at, OutboxEvent.created_at).limit(limit).all()
    
    def mark_processing(self, db: Session, event: OutboxEvent) -> bool:
        """
        Mark an event as currently being processed.
        
        Args:
            db: Database session
            event: Outbox event to mark
            
        Returns:
            bool: True if successfully marked, False if already being processed
        """
        # Use optimistic locking to prevent concurrent processing
        rows_updated = db.query(OutboxEvent).filter(
            and_(
                OutboxEvent.id == event.id,
                OutboxEvent.status.in_([EventStatus.PENDING.value, EventStatus.FAILED.value])
            )
        ).update({
            "status": EventStatus.PROCESSING.value,
            "processed_at": datetime.utcnow()
        })
        
        if rows_updated == 0:
            logger.warning(f"Event {event.id} already being processed or in wrong state")
            return False
            
        db.commit()
        logger.debug(f"Marked event {event.id} as processing")
        return True
    
    def mark_published(self, db: Session, event: OutboxEvent) -> None:
        """
        Mark an event as successfully published.
        
        Args:
            db: Database session
            event: Outbox event to mark as published
        """
        event.status = EventStatus.PUBLISHED.value
        event.processed_at = datetime.utcnow()
        event.last_error = None
        event.error_details = None
        
        db.commit()
        logger.info(f"Event {event.id} marked as published")
    
    def mark_failed(
        self,
        db: Session,
        event: OutboxEvent,
        error_message: str,
        error_details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Mark an event as failed and schedule retry if applicable.
        
        Args:
            db: Database session
            event: Outbox event to mark as failed
            error_message: Error message
            error_details: Additional error details
        """
        event.retry_count += 1
        event.last_error = error_message
        event.error_details = error_details or {}
        
        if event.retry_count >= event.max_retries:
            # Move to dead letter queue
            event.status = EventStatus.DEAD_LETTER.value
            logger.error(f"Event {event.id} moved to dead letter queue after {event.retry_count} retries")
        else:
            # Schedule retry with exponential backoff
            event.status = EventStatus.FAILED.value
            retry_delay = min(
                self.base_retry_delay * (2 ** (event.retry_count - 1)),
                self.max_retry_delay
            )
            event.next_retry_at = datetime.utcnow() + timedelta(seconds=retry_delay)
            
            logger.warning(
                f"Event {event.id} failed (attempt {event.retry_count}/{event.max_retries}), "
                f"retry scheduled in {retry_delay}s"
            )
        
        db.commit()
    
    def get_dead_letter_events(
        self,
        db: Session,
        limit: int = 100,
        hours: int = 24
    ) -> List[OutboxEvent]:
        """
        Get events in dead letter queue.
        
        Args:
            db: Database session
            limit: Maximum number of events
            hours: Only events from last N hours
            
        Returns:
            List of dead letter events
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        return db.query(OutboxEvent).filter(
            and_(
                OutboxEvent.status == EventStatus.DEAD_LETTER.value,
                OutboxEvent.created_at >= cutoff
            )
        ).order_by(OutboxEvent.created_at.desc()).limit(limit).all()
    
    def retry_dead_letter_event(self, db: Session, event_id: str) -> bool:
        """
        Retry a dead letter event (manual recovery).
        
        Args:
            db: Database session
            event_id: ID of event to retry
            
        Returns:
            bool: True if event was reset for retry
        """
        event = db.query(OutboxEvent).filter(OutboxEvent.id == event_id).first()
        
        if not event:
            logger.error(f"Event {event_id} not found")
            return False
        
        if event.status != EventStatus.DEAD_LETTER.value:
            logger.error(f"Event {event_id} is not in dead letter queue")
            return False
        
        # Reset for retry
        event.status = EventStatus.PENDING.value
        event.retry_count = 0
        event.next_retry_at = None
        event.last_error = None
        event.error_details = None
        
        db.commit()
        logger.info(f"Reset dead letter event {event_id} for retry")
        return True
    
    def get_outbox_statistics(self, db: Session, hours: int = 24) -> Dict[str, Any]:
        """
        Get outbox statistics for monitoring.
        
        Args:
            db: Database session
            hours: Time window for statistics
            
        Returns:
            Dict: Statistics summary
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        # Count by status
        stats = {}
        for status in EventStatus:
            count = db.query(OutboxEvent).filter(
                and_(
                    OutboxEvent.status == status.value,
                    OutboxEvent.created_at >= cutoff
                )
            ).count()
            stats[f"{status.value}_count"] = count
        
        # Overall statistics
        total_events = sum(stats.values())
        success_rate = (
            stats.get("published_count", 0) / max(total_events, 1) * 100
        )
        
        return {
            "time_window_hours": hours,
            "total_events": total_events,
            "success_rate_percent": round(success_rate, 2),
            "status_breakdown": stats,
            "timestamp": datetime.utcnow().isoformat()
        }

# Global service instance
outbox_service = OutboxService()