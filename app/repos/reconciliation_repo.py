from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.models.reconciliation import ReconciliationReport, DataMismatch


class ReconciliationRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def create_report(self) -> ReconciliationReport:
        """Create a new reconciliation report."""
        report = ReconciliationReport()
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report
    
    def get_latest_reports(self, limit: int = 10) -> List[ReconciliationReport]:
        """Get the most recent reconciliation reports."""
        return self.db.query(ReconciliationReport).order_by(desc(ReconciliationReport.started_at)).limit(limit).all()
    
    def get_report_with_mismatches(self, report_id: int) -> Optional[ReconciliationReport]:
        """Get a report by ID."""
        return self.db.query(ReconciliationReport).filter(ReconciliationReport.id == report_id).first()


class DataMismatchRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def create_mismatch(self, report_id: int, **kwargs) -> DataMismatch:
        """Create a new data mismatch record."""
        mismatch = DataMismatch(report_id=report_id, **kwargs)
        self.db.add(mismatch)
        self.db.commit()
        self.db.refresh(mismatch)
        return mismatch
    
    def get_by_report_id(self, report_id: int) -> List[DataMismatch]:
        """Get all mismatches for a specific report."""
        return self.db.query(DataMismatch).filter(DataMismatch.report_id == report_id).all()
    
    def get_pending_mismatches(self, limit: Optional[int] = None) -> List[DataMismatch]:
        """Get all pending mismatches across all reports."""
        query = self.db.query(DataMismatch).filter(DataMismatch.resolution_status == "pending")
        if limit:
            query = query.limit(limit)
        return query.all()
    
    def get_by_id(self, mismatch_id: int) -> Optional[DataMismatch]:
        """Get a mismatch by ID."""
        return self.db.query(DataMismatch).filter(DataMismatch.id == mismatch_id).first()
    
    def resolve_mismatch(self, mismatch_id: int, resolution_action: str) -> Optional[DataMismatch]:
        """Mark a mismatch as resolved."""
        mismatch = self.get_by_id(mismatch_id)
        if mismatch:
            mismatch.resolution_status = "manual_resolved"
            mismatch.resolution_action = resolution_action
            mismatch.resolved_at = self.db.query(self.db.func.now()).scalar()
            self.db.commit()
            self.db.refresh(mismatch)
        return mismatch