from fastapi import APIRouter, Depends, HTTPException, status, Header
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.core.database import get_db
from app.repos.customer_repo import customer_repo
from app.services.customer_service import customer_service
from app.models import customer as customer_model
from app.core.response import response_handler
from app.core.logger import logger

#dependencies
def get_customer_repo():
    return customer_repo

router = APIRouter(prefix="/customers", tags=["Customers"])

@router.post("/")
async def create_customer(
    customer: customer_model.CustomerCreate,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    use_integrity_protection: Optional[bool] = Header(False, alias="X-Use-Integrity-Protection")
):
    """
    Create customer with optional enhanced data integrity protection
    
    Headers:
    - Idempotency-Key: For safe retries (optional)
    - X-Use-Integrity-Protection: true/false to enable enhanced mode (default: false)
    """
    try:
        if use_integrity_protection:
            # Use enhanced mode with full integrity protection
            new_customer = await customer_service.create_customer_with_integrity(
                db=db, 
                customer=customer,
                idempotency_key=idempotency_key
            )
            message = "Customer created successfully with data integrity protection"
        else:
            # Use legacy mode for backward compatibility
            new_customer = customer_service.create_customer(db=db, customer=customer)
            message = "Customer created successfully"
            
        return response_handler.success(
            data=new_customer.model_dump(),
            message=message,
            status_code=status.HTTP_201_CREATED
        )
    except ValueError as e:
        return response_handler.failure(message=str(e), status_code=409)
    except RuntimeError as e:
        return response_handler.failure(message=str(e), status_code=500)
    except Exception as e:
        logger.error(f"Unexpected error in customer creation: {e}")
        return response_handler.failure(message="Internal server error", status_code=500)


@router.get("/")
def read_customers(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    customers = customer_service.get_all_customers(db, skip=skip, limit=limit)
    customers_in_db = [customer_model.CustomerInDB.from_orm(c).model_dump() for c in customers]
    return response_handler.success(data=customers_in_db)


@router.get("/{customer_id}")
def read_customer(
    customer_id: int,
    db: Session = Depends(get_db)
):
    db_customer = customer_service.get_customer(db, customer_id=customer_id)
    if db_customer is None:
        return response_handler.failure(message="Customer not found", status_code=404)
    return response_handler.success(data=customer_model.CustomerInDB.from_orm(db_customer).model_dump())


@router.put("/{customer_id}")
async def update_customer(
    customer_id: int,
    customer: customer_model.CustomerUpdate,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    use_integrity_protection: Optional[bool] = Header(False, alias="X-Use-Integrity-Protection")
):
    """Update customer with optional enhanced data integrity protection"""
    try:
        if use_integrity_protection:
            # Use enhanced mode
            updated_customer = await customer_service.update_customer_with_integrity(
                db=db,
                customer_id=customer_id,
                customer_update=customer,
                idempotency_key=idempotency_key
            )
            message = "Customer updated successfully with data integrity protection"
        else:
            # Use legacy mode
            updated_customer = customer_service.update_customer(db, customer_id, customer)
            message = "Customer updated successfully"
        
        if updated_customer is None:
            return response_handler.failure(message="Customer not found", status_code=404)
        
        return response_handler.success(
            data=updated_customer.model_dump(),
            message=message
        )
    except ValueError as e:
        return response_handler.failure(message=str(e), status_code=409)
    except RuntimeError as e:
        return response_handler.failure(message=str(e), status_code=500)
    except Exception as e:
        logger.error(f"Unexpected error in customer update: {e}")
        return response_handler.failure(message="Internal server error", status_code=500)


@router.delete("/{customer_id}")
async def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    use_integrity_protection: Optional[bool] = Header(False, alias="X-Use-Integrity-Protection")
):
    """Delete customer with optional enhanced data integrity protection"""
    try:
        if use_integrity_protection:
            # Use enhanced mode
            deleted = await customer_service.delete_customer_with_integrity(
                db=db,
                customer_id=customer_id,
                idempotency_key=idempotency_key
            )
            message = "Customer deleted successfully with data integrity protection"
        else:
            # Use legacy mode
            deleted = customer_service.delete_customer(db, customer_id=customer_id)
            message = "Customer deleted successfully"
        
        if not deleted:
            return response_handler.failure(message="Customer not found", status_code=404)
        
        return response_handler.success(
            data={"customer_id": customer_id, "deleted": True},
            message=message
        )
    except ValueError as e:
        return response_handler.failure(message=str(e), status_code=409)
    except RuntimeError as e:
        return response_handler.failure(message=str(e), status_code=500)
    except Exception as e:
        logger.error(f"Unexpected error in customer deletion: {e}")
        return response_handler.failure(message="Internal server error", status_code=500)


# Enhanced monitoring and maintenance endpoints
@router.get("/{customer_id}/sync-health")
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


@router.get("/integration-health/{integration_name}")
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


@router.post("/retry-failed-syncs")
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


@router.post("/cleanup-orphaned")
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