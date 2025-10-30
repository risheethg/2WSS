from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import json

from app.core.database import Base


class OutboxEvent(Base):
    """Outbox event for reliable message publishing"""
    __tablename__ = "outbox_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, nullable=False)  # e.g., "customer_created"
    entity_type = Column(String, nullable=False)  # e.g., "customer"
    entity_id = Column(String, nullable=False)   # The entity's ID (for partition key)
    payload = Column(Text, nullable=False)       # JSON payload
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)
    is_processed = Column(Boolean, default=False)
    retry_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)


class OutboxEventCreate(BaseModel):
    event_type: str
    entity_type: str
    entity_id: str
    payload: Dict[str, Any]
    
    def to_json_payload(self) -> str:
        """Convert payload to JSON string"""
        return json.dumps(self.payload)


class OutboxEventInDB(BaseModel):
    id: int
    event_type: str
    entity_type: str
    entity_id: str
    payload: str  # JSON string
    created_at: datetime
    processed_at: Optional[datetime] = None
    is_processed: bool
    retry_count: int
    last_error: Optional[str] = None

    class Config:
        from_attributes = True
    
    def get_payload(self) -> Dict[str, Any]:
        """Parse JSON payload back to dict"""
        return json.loads(self.payload)