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
    
    def handle_stripe_customer_upsert(self, db: Session, stripe_customer: dict):
        """Creates or updates a local customer from a Stripe webhook event."""
        stripe_customer_id = stripe_customer.get("id")
        # Check if we already have this customer linked by Stripe ID
        customer = customer_repo.get_by_stripe_id(db, stripe_id=stripe_customer_id)
        
        customer_data = customer_model.CustomerUpdate(
            name=stripe_customer.get("name"),
            email=stripe_customer.get("email")
        )

        if customer:
            # Update the existing customer
            print(f"Updating local customer {customer.id} from Stripe event.")
            customer_repo.update_by_stripe_id(db, stripe_id=stripe_customer_id, customer_data=customer_data)
        else:
            # If not found by Stripe ID, check by email to link accounts
            existing_by_email = customer_repo.get_by_email(db, email=customer_data.email)
            if existing_by_email:
                print(f"Linking existing local customer {existing_by_email.id} to Stripe ID {stripe_customer_id}.")
                existing_by_email.stripe_customer_id = stripe_customer_id
                db.commit()
            else:
                # If no customer exists, create a new one
                print(f"Creating new local customer from Stripe event for {customer_data.email}.")
                customer_repo.create_with_stripe_id(db, customer=customer_data, stripe_id=stripe_customer_id)

    def handle_stripe_customer_deleted(self, db: Session, stripe_customer: dict):
        """Deletes a local customer from a Stripe webhook event."""
        stripe_customer_id = stripe_customer.get("id")
        print(f"Deleting local customer linked to Stripe ID {stripe_customer_id}.")
        customer_repo.delete_by_stripe_id(db, stripe_id=stripe_customer_id)

customer_service = CustomerService()