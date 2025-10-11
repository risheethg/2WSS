from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.repos.customer_repo import customer_repo
from app.services.customer_service import customer_service
from app.models import customer as customer_model
from app.core.response import response_handler

#dependencies
def get_customer_repo():
    return customer_repo

router = APIRouter(prefix="/customers", tags=["customers"])

@router.post("/")
def create_customer(
    customer: customer_model.CustomerCreate,
    db: Session = Depends(get_db)
):
    try:
        new_customer = customer_service.create_customer(db=db, customer=customer)
        return response_handler.success(
            data=new_customer.model_dump(),  # CustomerInDB from service
            message="Customer created successfully",
            status_code=status.HTTP_201_CREATED
        )
    except ValueError as e:
        # Handle repository errors (e.g., active customer already exists)
        return response_handler.failure(message=str(e), status_code=409)


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
def update_customer(
    customer_id: int,
    customer: customer_model.CustomerUpdate,
    db: Session = Depends(get_db)
):
    db_customer = customer_service.update_customer(db, customer_id, customer)
    if db_customer is None:
        return response_handler.failure(message="Customer not found", status_code=404)
    return response_handler.success(
        data=customer_model.CustomerInDB.from_orm(db_customer).model_dump(),
        message="Customer updated successfully"
    )


@router.delete("/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db)
):
    deleted = customer_service.delete_customer(db, customer_id=customer_id)
    if not deleted:
        return response_handler.failure(message="Customer not found", status_code=404)
    return response_handler.success(
        data={"customer_id": customer_id, "deleted": True},
        message="Customer deleted successfully"
    )