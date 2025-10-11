from datetime import datetime
from typing import Dict, Any, Optional, List
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from app.core.database import Base


class ReconciliationReport(Base):
    __tablename__ = "reconciliation_reports"
    
    id = Column(Integer, primary_key=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running")  # running, completed, failed
    total_local_customers = Column(Integer, default=0)
    total_stripe_customers = Column(Integer, default=0)
    mismatches_found = Column(Integer, default=0)
    auto_resolved = Column(Integer, default=0)
    manual_review_needed = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)


class DataMismatch(Base):
    __tablename__ = "data_mismatches"
    
    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(Integer, index=True)
    customer_id = Column(Integer, nullable=True)  # Local customer ID
    stripe_customer_id = Column(String, nullable=True)  # Stripe customer ID
    email = Column(String, index=True)  # For matching
    mismatch_type = Column(String(50))  # field_mismatch, missing_in_stripe, missing_in_local
    field_name = Column(String(100), nullable=True)  # Which field differs
    local_value = Column(Text, nullable=True)
    stripe_value = Column(Text, nullable=True)
    resolution_status = Column(String(20), default="pending")  # pending, auto_resolved, manual_resolved, ignored
    resolution_action = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)


# Pydantic models for API
from pydantic import BaseModel
from typing import Optional


class DataMismatchResponse(BaseModel):
    id: int
    customer_id: Optional[int]
    stripe_customer_id: Optional[str]
    email: str
    mismatch_type: str
    field_name: Optional[str]
    local_value: Optional[str]
    stripe_value: Optional[str]
    resolution_status: str
    resolution_action: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


class ReconciliationReportResponse(BaseModel):
    id: int
    started_at: datetime
    completed_at: Optional[datetime]
    status: str
    total_local_customers: int
    total_stripe_customers: int
    mismatches_found: int
    auto_resolved: int
    manual_review_needed: int
    error_message: Optional[str]
    
    class Config:
        from_attributes = True


class ReconciliationSummary(BaseModel):
    report: ReconciliationReportResponse
    mismatches: List[DataMismatchResponse]