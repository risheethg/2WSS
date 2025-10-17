from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.services.reconciliation_service import ReconciliationService
from app.services.reconciliation_scheduler import get_scheduler
from app.models.reconciliation import (
    ReconciliationReportResponse, 
    ReconciliationSummary,
    DataMismatchResponse
)
from app.repos.reconciliation_repo import DataMismatchRepository
from app.core.logger import logger

router = APIRouter(prefix="/admin/reconciliation", tags=["reconciliation"])


@router.post("/run", response_model=dict)
async def trigger_reconciliation(
    auto_resolve: bool = Query(True, description="Automatically resolve simple mismatches (ADDITIVE ONLY)"),
    sync_to_stripe: bool = Query(True, description="Auto-sync missing local customers to Stripe"),
    sync_to_local: bool = Query(False, description="Auto-sync missing Stripe customers to local (requires manual approval)"),
    db: Session = Depends(get_db)
):
    """
    Manually trigger a reconciliation between local and Stripe customer data.
    
    ADDITIVE RECONCILIATION - Only creates missing data, never deletes:
    - **auto_resolve**: If true, automatically fixes simple mismatches like missing Stripe IDs
    - **sync_to_stripe**: If true, creates missing customers in Stripe from local data
    - **sync_to_local**: If true, creates missing customers locally from Stripe data (use carefully)
    - Returns a summary of the reconciliation results
    """
    try:
        reconciliation_service = ReconciliationService(db)
        report = await reconciliation_service.run_reconciliation(
            auto_resolve=auto_resolve,
            auto_sync_to_stripe=sync_to_stripe,
            auto_sync_to_local=sync_to_local
        )
        
        return {
            "success": True,
            "message": "Reconciliation completed successfully (ADDITIVE MODE)",
            "report_id": report.id,
            "total_local_customers": report.total_local_customers,
            "total_stripe_customers": report.total_stripe_customers,
            "mismatches_found": report.mismatches_found,
            "auto_resolved": report.auto_resolved,
            "manual_review_needed": report.manual_review_needed,
            "status": report.status,
            "note": "Reconciliation is ADDITIVE ONLY - no data was deleted"
        }
    
    except Exception as e:
        logger.error(f"Manual reconciliation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Reconciliation failed: {str(e)}")


@router.get("/reports", response_model=List[ReconciliationReportResponse])
async def get_reconciliation_reports(
    limit: int = Query(10, ge=1, le=50, description="Number of reports to return"),
    db: Session = Depends(get_db)
):
    """
    Get the most recent reconciliation reports.
    
    - **limit**: Number of reports to return (1-50, default 10)
    """
    try:
        reconciliation_service = ReconciliationService(db)
        reports = await reconciliation_service.get_latest_reports(limit=limit)
        
        return [ReconciliationReportResponse.from_orm(report) for report in reports]
    
    except Exception as e:
        logger.error(f"Failed to get reconciliation reports: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get reports: {str(e)}")


@router.get("/reports/{report_id}", response_model=ReconciliationSummary)
async def get_reconciliation_report(
    report_id: int,
    db: Session = Depends(get_db)
):
    """
    Get detailed information about a specific reconciliation report including all mismatches.
    
    - **report_id**: ID of the reconciliation report
    """
    try:
        reconciliation_service = ReconciliationService(db)
        summary = await reconciliation_service.get_reconciliation_summary(report_id)
        
        if not summary:
            raise HTTPException(status_code=404, detail="Reconciliation report not found")
        
        return summary
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get reconciliation report {report_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get report: {str(e)}")


@router.get("/mismatches", response_model=List[DataMismatchResponse])
async def get_pending_mismatches(
    limit: Optional[int] = Query(None, ge=1, le=100, description="Maximum number of mismatches to return"),
    db: Session = Depends(get_db)
):
    """
    Get all pending data mismatches that need manual review across all reconciliation reports.
    
    - **limit**: Maximum number of mismatches to return (optional)
    """
    try:
        mismatch_repo = DataMismatchRepository(db)
        mismatches = mismatch_repo.get_pending_mismatches(limit=limit)
        
        return [DataMismatchResponse.from_orm(mismatch) for mismatch in mismatches]
    
    except Exception as e:
        logger.error(f"Failed to get pending mismatches: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get mismatches: {str(e)}")


@router.post("/mismatches/{mismatch_id}/resolve", response_model=dict)
async def resolve_mismatch(
    mismatch_id: int,
    resolution_action: str = Query(..., description="Action: sync_to_local, sync_to_stripe, link_existing, or custom description"),
    db: Session = Depends(get_db)
):
    """
    Resolve a data mismatch with actual sync operations (ADDITIVE ONLY).
    
    - **mismatch_id**: ID of the mismatch to resolve
    - **resolution_action**: 
      - "sync_to_local": Create customer in local DB from Stripe data
      - "sync_to_stripe": Create customer in Stripe from local data  
      - "link_existing": Link existing customers by updating Stripe ID
      - Custom description for manual resolution
      
    **ADDITIVE ONLY**: No data will be deleted, only created or linked.
    """
    try:
        reconciliation_service = ReconciliationService(db)
        resolved_mismatch = await reconciliation_service.resolve_mismatch(mismatch_id, resolution_action)
        
        if not resolved_mismatch:
            raise HTTPException(status_code=404, detail="Mismatch not found")
        
        return {
            "success": True,
            "message": "Mismatch resolved with sync operation (ADDITIVE ONLY)",
            "mismatch_id": mismatch_id,
            "resolution_action": resolution_action,
            "resolved_at": resolved_mismatch.resolved_at.isoformat() if resolved_mismatch.resolved_at else None,
            "note": "No data was deleted - only created or linked"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to resolve mismatch {mismatch_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to resolve mismatch: {str(e)}")


@router.get("/status", response_model=dict)
async def get_reconciliation_status():
    """
    Get the current status of the reconciliation scheduler.
    
    Returns information about when the next reconciliation is scheduled.
    """
    try:
        scheduler = await get_scheduler()
        
        return {
            "scheduler_running": scheduler.is_running,
            "message": "Reconciliation scheduler is running" if scheduler.is_running else "Reconciliation scheduler is stopped"
        }
    
    except Exception as e:
        logger.error(f"Failed to get reconciliation status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@router.post("/scheduler/start", response_model=dict)
async def start_reconciliation_scheduler():
    """
    Start the automatic reconciliation scheduler.
    
    The scheduler will run reconciliation at the configured time (default: 2:00 AM daily).
    """
    try:
        scheduler = await get_scheduler()
        
        if scheduler.is_running:
            return {
                "success": True,
                "message": "Reconciliation scheduler is already running"
            }
        
        await scheduler.start_scheduler()
        
        return {
            "success": True,
            "message": "Reconciliation scheduler started successfully"
        }
    
    except Exception as e:
        logger.error(f"Failed to start reconciliation scheduler: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {str(e)}")


@router.post("/scheduler/stop", response_model=dict)
async def stop_reconciliation_scheduler():
    """
    Stop the automatic reconciliation scheduler.
    
    This will cancel any pending scheduled reconciliation.
    """
    try:
        scheduler = await get_scheduler()
        
        if not scheduler.is_running:
            return {
                "success": True,
                "message": "Reconciliation scheduler is already stopped"
            }
        
        await scheduler.stop_scheduler()
        
        return {
            "success": True,
            "message": "Reconciliation scheduler stopped successfully"
        }
    
    except Exception as e:
        logger.error(f"Failed to stop reconciliation scheduler: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to stop scheduler: {str(e)}")