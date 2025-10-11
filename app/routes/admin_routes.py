from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from app.core.database import get_db
from app.services.customer_service import customer_service
from app.core.response import response_handler
from app.core.logger import logger

router = APIRouter(prefix="/admin", tags=["Admin & Monitoring"])

# =============================================================================
# MONITORING ENDPOINTS
# =============================================================================

@router.get("/customers/{customer_id}/sync-health")
def get_customer_sync_health(
    customer_id: int,
    db: Session = Depends(get_db)
):
    """Get synchronization health status for a customer across all integrations"""
    try:
        health_status = customer_service.get_customer_sync_health(db, customer_id)
        return response_handler.success(
            data={
                "customer_id": customer_id,
                "integration_status": health_status
            },
            message="Customer sync health retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error retrieving customer sync health: {e}")
        return response_handler.failure(message="Failed to retrieve sync health", status_code=500)


@router.get("/integrations/{integration_name}/health")
def get_integration_health(
    integration_name: str,
    db: Session = Depends(get_db)
):
    """Get health statistics for a specific integration"""
    try:
        health_stats = customer_service.get_integration_health(db, integration_name)
        return response_handler.success(
            data=health_stats,
            message=f"Integration health for {integration_name} retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error retrieving integration health: {e}")
        return response_handler.failure(message="Failed to retrieve integration health", status_code=500)


# =============================================================================
# MAINTENANCE ENDPOINTS
# =============================================================================

@router.post("/maintenance/retry-failed-syncs")
async def retry_failed_syncs(
    integration_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Retry failed synchronizations for all or specific integration"""
    try:
        retried_count = await customer_service.retry_failed_syncs(db, integration_name)
        return response_handler.success(
            data={
                "integration": integration_name or "all",
                "retried_count": retried_count
            },
            message=f"Retried {retried_count} failed synchronizations"
        )
    except Exception as e:
        logger.error(f"Error retrying failed syncs: {e}")
        return response_handler.failure(message="Failed to retry synchronizations", status_code=500)


@router.post("/maintenance/cleanup-orphaned")
def cleanup_orphaned_records(
    integration_name: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Clean up orphaned integration records"""
    try:
        cleaned_count = customer_service.cleanup_orphaned_records(db, integration_name)
        return response_handler.success(
            data={
                "integration": integration_name or "all",
                "cleaned_count": cleaned_count
            },
            message=f"Cleaned up {cleaned_count} orphaned records"
        )
    except Exception as e:
        logger.error(f"Error cleaning up orphaned records: {e}")
        return response_handler.failure(message="Failed to clean up orphaned records", status_code=500)


# =============================================================================
# DATABASE HEALTH MONITORING ENDPOINTS  
# =============================================================================

@router.get("/database/health")
def get_database_health():
    """Get comprehensive database health status and metrics"""
    from app.core.db_monitoring import db_monitor
    try:
        dashboard_data = db_monitor.get_monitoring_dashboard()
        return response_handler.success(
            data=dashboard_data,
            message="Database health status retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error retrieving database health: {e}")
        return response_handler.failure(message="Failed to retrieve database health", status_code=500)


@router.get("/database/metrics")
def get_database_metrics():
    """Get detailed database performance metrics"""
    from app.core.db_monitoring import db_monitor
    try:
        metrics = db_monitor.get_database_metrics()
        return response_handler.success(
            data=metrics.to_dict(),
            message="Database metrics retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error retrieving database metrics: {e}")
        return response_handler.failure(message="Failed to retrieve database metrics", status_code=500)


@router.post("/database/diagnostics")
def run_database_diagnostics(db: Session = Depends(get_db)):
    """Run comprehensive database diagnostics"""
    from app.core.db_monitoring import db_monitor
    try:
        diagnostics = db_monitor.run_database_diagnostics(db)
        return response_handler.success(
            data=diagnostics,
            message="Database diagnostics completed successfully"
        )
    except Exception as e:
        logger.error(f"Error running database diagnostics: {e}")
        return response_handler.failure(message="Failed to run database diagnostics", status_code=500)


@router.get("/database/deadlocks")
def get_deadlock_statistics():
    """Get deadlock statistics and prevention recommendations"""
    from app.core.deadlock_detector import deadlock_detector
    try:
        stats = deadlock_detector.get_deadlock_statistics(hours=24)
        recommendations = deadlock_detector.get_deadlock_prevention_recommendations()
        
        return response_handler.success(
            data={
                "statistics": stats,
                "prevention_recommendations": recommendations
            },
            message="Deadlock statistics retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error retrieving deadlock statistics: {e}")
        return response_handler.failure(message="Failed to retrieve deadlock statistics", status_code=500)


@router.get("/database/connection-pool")
def get_connection_pool_status():
    """Get connection pool status and health"""
    from app.core.database import DatabaseHealthChecker
    try:
        health_status = DatabaseHealthChecker.check_connection_health()
        pool_status = DatabaseHealthChecker.get_pool_status()
        
        return response_handler.success(
            data={
                "health": health_status,
                "pool_status": pool_status
            },
            message="Connection pool status retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error retrieving connection pool status: {e}")
        return response_handler.failure(message="Failed to retrieve connection pool status", status_code=500)


# =============================================================================
# DATA CONSISTENCY ENDPOINTS
# =============================================================================

@router.get("/data-consistency/validate")
def validate_data_consistency(db: Session = Depends(get_db)):
    """
    Validate data consistency across the system
    
    This endpoint checks for:
    - Customers with missing integration sync states
    - Sync states without corresponding customers
    - Integration ID conflicts
    - Email uniqueness violations
    """
    try:
        from app.models.customer import Customer
        from app.models.integrity import IntegrationSyncState
        from sqlalchemy import func
        
        issues = []
        
        # Check for customers without sync states
        customers_without_sync = db.query(Customer).outerjoin(IntegrationSyncState).filter(
            Customer.is_active == True,
            IntegrationSyncState.id.is_(None)
        ).all()
        
        if customers_without_sync:
            issues.append({
                "type": "missing_sync_states",
                "count": len(customers_without_sync),
                "customer_ids": [c.id for c in customers_without_sync[:10]]  # First 10 as sample
            })
        
        # Check for sync states without customers
        orphaned_sync_states = db.query(IntegrationSyncState).outerjoin(Customer).filter(
            Customer.id.is_(None)
        ).all()
        
        if orphaned_sync_states:
            issues.append({
                "type": "orphaned_sync_states",
                "count": len(orphaned_sync_states),
                "sync_state_ids": [s.id for s in orphaned_sync_states[:10]]
            })
        
        # Check for duplicate emails among active customers
        duplicate_emails = db.query(
            Customer.email,
            func.count(Customer.id).label('count')
        ).filter(
            Customer.is_active == True
        ).group_by(Customer.email).having(
            func.count(Customer.id) > 1
        ).all()
        
        if duplicate_emails:
            issues.append({
                "type": "duplicate_emails",
                "count": len(duplicate_emails),
                "emails": [email for email, count in duplicate_emails[:10]]
            })
        
        # Check for Stripe ID conflicts
        duplicate_stripe_ids = db.query(
            Customer.stripe_customer_id,
            func.count(Customer.id).label('count')
        ).filter(
            Customer.stripe_customer_id.isnot(None),
            Customer.is_active == True
        ).group_by(Customer.stripe_customer_id).having(
            func.count(Customer.id) > 1
        ).all()
        
        if duplicate_stripe_ids:
            issues.append({
                "type": "duplicate_stripe_ids",
                "count": len(duplicate_stripe_ids),
                "stripe_ids": [stripe_id for stripe_id, count in duplicate_stripe_ids[:10]]
            })
        
        return response_handler.success(
            data={
                "validation_timestamp": str(datetime.utcnow()),
                "issues_found": len(issues),
                "issues": issues
            },
            message="Data consistency validation completed"
        )
        
    except Exception as e:
        logger.error(f"Error validating data consistency: {e}")
        return response_handler.failure(message="Failed to validate data consistency", status_code=500)


@router.post("/data-consistency/fix")
def fix_data_consistency_issues(db: Session = Depends(get_db)):
    """
    Attempt to fix common data consistency issues
    
    This is a maintenance endpoint that should be used carefully
    """
    try:
        from app.models.customer import Customer
        from app.models.integrity import IntegrationSyncState
        from app.services.sync_service import sync_service
        
        fixed_issues = []
        
        # Fix customers without sync states
        customers_without_sync = db.query(Customer).outerjoin(IntegrationSyncState).filter(
            Customer.is_active == True,
            IntegrationSyncState.id.is_(None)
        ).all()
        
        for customer in customers_without_sync:
            try:
                sync_service.create_sync_state(
                    db, customer.id, "stripe", 
                    external_id=customer.stripe_customer_id, 
                    sync_status="synced" if customer.stripe_customer_id else "pending"
                )
                fixed_issues.append(f"Created sync state for customer {customer.id}")
            except Exception as e:
                logger.error(f"Failed to create sync state for customer {customer.id}: {e}")
        
        # Clean up orphaned sync states
        orphaned_sync_states = db.query(IntegrationSyncState).outerjoin(Customer).filter(
            Customer.id.is_(None)
        ).all()
        
        for sync_state in orphaned_sync_states:
            try:
                db.delete(sync_state)
                db.commit()
                fixed_issues.append(f"Removed orphaned sync state {sync_state.id}")
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to remove orphaned sync state {sync_state.id}: {e}")
        
        return response_handler.success(
            data={
                "fixed_issues": fixed_issues,
                "total_fixes": len(fixed_issues)
            },
            message=f"Fixed {len(fixed_issues)} data consistency issues"
        )
        
    except Exception as e:
        logger.error(f"Error fixing data consistency issues: {e}")
        return response_handler.failure(message="Failed to fix data consistency issues", status_code=500)