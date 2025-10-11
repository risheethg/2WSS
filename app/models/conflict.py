"""
Conflict Resolution Models

Tracks data conflicts that occur during webhook processing for manual resolution.
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Enum
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum as PyEnum
import json

from app.core.database import Base


class ConflictStatus(PyEnum):
    PENDING = "pending"
    RESOLVED = "resolved" 
    REJECTED = "rejected"


class ConflictResolutionStrategy(PyEnum):
    REJECT = "reject"           # Reject the conflicting change
    MERGE = "merge"             # Merge the accounts
    FLAG_FOR_REVIEW = "flag"    # Flag for manual review
    AUTO_RENAME = "auto_rename" # Automatically rename to avoid conflict


class DataConflict(Base):
    """Data conflict tracking for webhook processing"""
    __tablename__ = "data_conflicts"

    id = Column(Integer, primary_key=True, index=True)
    conflict_type = Column(String, nullable=False)  # e.g., "email_constraint"
    entity_type = Column(String, nullable=False)    # e.g., "customer"
    external_system = Column(String, nullable=False) # e.g., "stripe"
    external_id = Column(String, nullable=False)     # e.g., stripe_customer_id
    
    # Conflict details
    conflict_field = Column(String, nullable=False)  # e.g., "email"
    conflict_value = Column(String, nullable=False)  # The conflicting value
    existing_entity_id = Column(Integer, nullable=True) # ID of existing conflicting entity
    
    # Webhook event data
    webhook_event_data = Column(Text, nullable=False) # JSON of the webhook event
    error_message = Column(Text, nullable=False)
    
    # Resolution tracking
    status = Column(String, default=ConflictStatus.PENDING.value)
    resolution_strategy = Column(String, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolved_by = Column(String, nullable=True)  # Could be "auto" or admin user
    resolution_notes = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


class ConflictCreate(BaseModel):
    conflict_type: str
    entity_type: str
    external_system: str
    external_id: str
    conflict_field: str
    conflict_value: str
    existing_entity_id: Optional[int] = None
    webhook_event_data: Dict[str, Any]
    error_message: str


class ConflictInDB(BaseModel):
    id: int
    conflict_type: str
    entity_type: str
    external_system: str
    external_id: str
    conflict_field: str
    conflict_value: str
    existing_entity_id: Optional[int] = None
    webhook_event_data: str  # JSON string
    error_message: str
    status: str
    resolution_strategy: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
    
    def get_webhook_data(self) -> Dict[str, Any]:
        """Parse webhook event data from JSON"""
        return json.loads(self.webhook_event_data)


class ConflictResolution(BaseModel):
    strategy: ConflictResolutionStrategy
    notes: Optional[str] = None
    resolved_by: str = "admin"