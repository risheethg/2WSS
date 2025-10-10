from sqlalchemy.orm import Session
from typing import List, Optional
from app.repos.customer_repo import customer_repo
from app.models import customer as customer_model
from app.models.customer import CustomerInDB
from app.core import messaging

class CustomerService:
    def create_customer(self, db: Session, customer: customer_model.CustomerCreate) -> customer_model.Customer:
        db_customer = customer_repo.create(db, customer)
        customer_data = CustomerInDB.from_orm(db_customer).model_dump()
        messaging.send_customer_event("customer_created", customer_data)
        return db_customer

    def update_customer(self, db: Session, customer_id: int, customer_update: customer_model.CustomerUpdate) -> Optional[customer_model.Customer]:
        updated_customer = customer_repo.update(db, customer_id, customer_update)
        if updated_customer:
            customer_data = CustomerInDB.from_orm(updated_customer).model_dump()
            messaging.send_customer_event("customer_updated", customer_data)
        return updated_customer

    def delete_customer(self, db: Session, customer_id: int) -> Optional[customer_model.Customer]:
        deleted_customer = customer_repo.delete(db, customer_id)
        if deleted_customer:
            # Handle soft delete logic here if you added it
            customer_data = CustomerInDB.from_orm(deleted_customer).model_dump()
            messaging.send_customer_event("customer_deleted", customer_data)
        return deleted_customer

    def get_customer(self, db: Session, customer_id: int) -> Optional[customer_model.Customer]:
        return customer_repo.get(db, customer_id)

    def get_all_customers(self, db: Session, skip: int = 0, limit: int = 100) -> List[customer_model.Customer]:
        return customer_repo.get_all(db, skip, limit)
    
customer_service = CustomerService()