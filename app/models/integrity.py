from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON, func, UniqueConstraint
from sqlalchemy.orm import relationship
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from app.core.database import Base


class IntegrationSyncState(Base):
    """Track sync state between local customers and external integrations"""
    __tablename__ = "integration_sync_state"
    
    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    integration_name = Column(String(50), nullable=False)
    external_id = Column(String(255), nullable=True, index=True)
    sync_status = Column(String(20), nullable=False, default="pending")  # pending, synced, failed, orphaned
    last_sync_attempt = Column(DateTime, nullable=True)
    retry_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    
    # Ensure one sync state per customer per integration
    __table_args__ = (UniqueConstraint('customer_id', 'integration_name', name='uq_customer_integration'),)
    
    # Relationship to customer
    customer = relationship("Customer", back_populates="integration_sync_states")


class IdempotencyKey(Base):
    """Store idempotency keys to prevent duplicate operations"""
    __tablename__ = "idempotency_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), nullable=False, unique=True, index=True)
    operation_type = Column(String(50), nullable=False)  # create_customer, update_customer, delete_customer
    resource_id = Column(String(100), nullable=True)
    request_hash = Column(String(64), nullable=True)
    response_data = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="processing")  # processing, completed, failed
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)


# Pydantic models
class IntegrationSyncStateBase(BaseModel):
    customer_id: int
    integration_name: str
    external_id: Optional[str] = None
    sync_status: str = "pending"
    retry_count: int = 0
    error_message: Optional[str] = None


class IntegrationSyncStateCreate(IntegrationSyncStateBase):
    pass


class IntegrationSyncStateUpdate(BaseModel):
    external_id: Optional[str] = None
    sync_status: Optional[str] = None
    last_sync_attempt: Optional[datetime] = None
    retry_count: Optional[int] = None
    error_message: Optional[str] = None


class IntegrationSyncStateInDB(IntegrationSyncStateBase):
    id: int
    last_sync_attempt: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class IdempotencyKeyBase(BaseModel):
    key: str
    operation_type: str
    resource_id: Optional[str] = None
    request_hash: Optional[str] = None


class IdempotencyKeyCreate(IdempotencyKeyBase):
    expires_at: datetime = None
    
    def __init__(self, **data):
        if data.get('expires_at') is None:
            data['expires_at'] = datetime.utcnow() + timedelta(hours=24)
        super().__init__(**data)


class IdempotencyKeyInDB(IdempotencyKeyBase):
    id: int
    response_data: Optional[Dict[str, Any]] = None
    status: str
    created_at: datetime
    expires_at: datetime
    
    class Config:
        from_attributes = True