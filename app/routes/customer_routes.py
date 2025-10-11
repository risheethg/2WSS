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


# Note: Monitoring and maintenance endpoints moved to admin_routes.py for better separation of concerns