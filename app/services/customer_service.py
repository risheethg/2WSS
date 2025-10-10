from sqlalchemy.orm import Session
from typing import List, Optional
from app.repos.customer_repo import customer_repo
from app.models import customer as customer_model

class CustomerService:
    def create_customer(self, db: Session, customer: customer_model.CustomerCreate) -> customer_model.Customer:
        # To do: Add logic to publish a 'customer_created' event to Kafka here
        return customer_repo.create(db, customer)

    def get_customer(self, db: Session, customer_id: int) -> Optional[customer_model.Customer]:
        return customer_repo.get(db, customer_id)

    def get_all_customers(self, db: Session, skip: int = 0, limit: int = 100) -> List[customer_model.Customer]:
        return customer_repo.get_all(db, skip, limit)

    def update_customer(self, db: Session, customer_id: int, customer_update: customer_model.CustomerUpdate) -> Optional[customer_model.Customer]:
        # To do: Add logic to publish a 'customer_updated' event to Kafka here
        updated_customer = customer_repo.update(db, customer_id, customer_update)
        return updated_customer

    def delete_customer(self, db: Session, customer_id: int) -> Optional[customer_model.Customer]:
        # To do: Add logic to publish a 'customer_deleted' event to Kafka here
        deleted_customer = customer_repo.delete(db, customer_id)
        return deleted_customer

customer_service = CustomerService()