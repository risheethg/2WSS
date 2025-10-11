"""
Transactional Outbox Pattern Implementation

This module implements the transactional outbox pattern to ensure reliable event publishing.
The outbox pattern guarantees that events are only published if the database transaction succeeds.

Key components:
- OutboxEvent model for storing events to be published
- OutboxProcessor for publishing events to Kafka
- OutboxService for managing outbox operations
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime
import uuid
import json
import logging
from typing import Dict, Any, Optional, List
from enum import Enum

from app.core.database import Base

logger = logging.getLogger(__name__)

class EventStatus(Enum):
    """Status of outbox events."""
    PENDING = "pending"
    PROCESSING = "processing" 
    PUBLISHED = "published"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"

class OutboxEvent(Base):
    """
    Outbox event table for transactional event publishing.
    
    This table stores events that need to be published to Kafka within the same
    database transaction as the business operation, ensuring consistency.
    """
    __tablename__ = "outbox_events"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Event identification
    event_type = Column(String(100), nullable=False, index=True)  # e.g., "customer_created"
    aggregate_id = Column(String(100), nullable=False, index=True)  # e.g., customer_id
    aggregate_type = Column(String(50), nullable=False, index=True)  # e.g., "customer"
    
    # Kafka routing
    topic = Column(String(100), nullable=False)  # Kafka topic
    partition_key = Column(String(100), nullable=False, index=True)  # For message ordering
    
    # Event data
    payload = Column(JSONB, nullable=False)  # Event payload as JSON
    metadata = Column(JSONB, nullable=True)  # Additional metadata
    
    # Status tracking  
    status = Column(String(20), nullable=False, default=EventStatus.PENDING.value, index=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=5)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)
    next_retry_at = Column(DateTime, nullable=True)
    
    # Error tracking
    last_error = Column(Text, nullable=True)
    error_details = Column(JSONB, nullable=True)
    
    # Indexes for performance
    __table_args__ = (
        Index('idx_outbox_status_next_retry', 'status', 'next_retry_at'),
        Index('idx_outbox_aggregate', 'aggregate_type', 'aggregate_id'),
        Index('idx_outbox_created_at', 'created_at'),
        Index('idx_outbox_partition_key', 'partition_key'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "event_type": self.event_type,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "topic": self.topic,
            "partition_key": self.partition_key,
            "payload": self.payload,
            "metadata": self.metadata,
            "status": self.status,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "last_error": self.last_error,
            "error_details": self.error_details
        }
    
    def is_ready_for_retry(self) -> bool:
        """Check if event is ready for retry."""
        if self.status != EventStatus.FAILED.value:
            return False
        if self.retry_count >= self.max_retries:
            return False
        if self.next_retry_at and datetime.utcnow() < self.next_retry_at:
            return False
        return True
    
    def should_move_to_dlq(self) -> bool:
        """Check if event should be moved to dead letter queue."""
        return (
            self.status == EventStatus.FAILED.value and 
            self.retry_count >= self.max_retries
        )