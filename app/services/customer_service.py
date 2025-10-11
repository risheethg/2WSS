import asyncio
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from sqlalchemy.exc import IntegrityError

from app.repos.customer_repo import customer_repo
from app.repos.base import repository_registry
from app.models import customer as customer_model
from app.models.customer import CustomerInDB
from app.core import messaging
from app.core.locking import customer_lock, email_lock, integration_lock, lock_service
from app.core.idempotency import idempotency_service, with_idempotency
from app.core.transactions import CustomerTransactionContext, create_db_rollback, create_integration_rollback
from app.services.sync_service import sync_service
from app.integrations.registry import integration_registry
from app.core.logger import logger

class CustomerService:
    def __init__(self):
        self.max_retries = 3
        self.base_delay = 1.0
    
    async def initialize(self):
        """Initialize the service and its dependencies"""
        if not lock_service._initialized:
            await lock_service.initialize()
    
    def create_customer(self, db: Session, customer: customer_model.CustomerCreate) -> CustomerInDB:
        """Create customer using new repository interface (legacy method)"""
        customer_in_db = customer_repo.create(db, customer)
        customer_data = customer_in_db.model_dump()
        messaging.send_customer_event("customer_created", customer_data)
        return customer_in_db
    
    async def create_customer_with_integrity(
        self,
        db: Session,
        customer: customer_model.CustomerCreate,
        idempotency_key: str = None
    ) -> CustomerInDB:
        """
        Create customer with full data integrity protection
        
        This method implements:
        - Email-based locking to prevent race conditions
        - Idempotency to prevent duplicate creations
        - Distributed transactions with rollback
        - Integration state tracking
        """
        await self.initialize()
        
        if not idempotency_key:
            idempotency_key = idempotency_service.generate_key(
                "create_customer", f"email:{customer.email}"
            )
        
        # Check for duplicate request
        is_duplicate, existing_key = idempotency_service.is_duplicate_request(
            db, idempotency_key, {"email": customer.email, "name": customer.name}
        )
        
        if is_duplicate and existing_key:
            if existing_key.status == "completed":
                logger.info(f"Returning cached result for customer creation: {customer.email}")
                return CustomerInDB(**existing_key.response_data["result"])
            elif existing_key.status == "processing":
                raise ValueError("Customer creation already in progress")
        
        # Create idempotency key
        if not existing_key:
            idempotency_service.create_idempotency_key(
                db, idempotency_key, "create_customer", 
                {"email": customer.email, "name": customer.name}
            )
        
        # Use email-based distributed lock
        async with email_lock(customer.email, timeout=30):
            try:
                # Validate email is not already taken (with soft-delete awareness)
                await self._validate_email_uniqueness(db, customer.email)
                
                # Create transaction context
                transaction_id = f"create_customer_{uuid.uuid4().hex[:8]}"
                
                with CustomerTransactionContext(transaction_id) as tx_context:
                    created_customer = None
                    
                    # Step 1: Create customer in database
                    def create_in_db():
                        nonlocal created_customer
                        created_customer = customer_repo.create(db, customer)
                        sync_service.create_sync_state(
                            db, created_customer.id, "stripe", sync_status="pending"
                        )
                        return created_customer
                    
                    def rollback_db_create():
                        if created_customer:
                            customer_repo.delete(db, created_customer.id)
                            sync_service.delete_sync_state(db, created_customer.id, "stripe")
                    
                    tx_context.add_local_db_step(
                        "create_customer_db",
                        create_in_db,
                        rollback_db_create
                    )
                    
                    # Step 2: Send to message queue
                    def send_to_queue():
                        if created_customer:
                            customer_data = created_customer.model_dump()
                            messaging.send_customer_event("customer_created", customer_data)
                        return True
                    
                    def rollback_queue():
                        # For queue operations, we rely on the worker's idempotency
                        # and the sync state tracking to handle failures
                        pass
                    
                    tx_context.add_integration_step(
                        "send_create_event",
                        send_to_queue,
                        rollback_queue
                    )
                    
                    # Execute transaction
                    success = await tx_context.execute()
                    
                    if success and created_customer:
                        # Mark idempotency key as completed
                        idempotency_service.update_idempotency_key(
                            db, idempotency_key, "completed", 
                            {"result": created_customer.model_dump()}
                        )
                        
                        logger.info(f"Customer created successfully with integrity protection: {customer.email}")
                        return created_customer
                    else:
                        # Mark idempotency key as failed
                        idempotency_service.update_idempotency_key(
                            db, idempotency_key, "failed", 
                            error_message="Transaction execution failed"
                        )
                        raise RuntimeError("Customer creation transaction failed")
                        
            except Exception as e:
                # Mark idempotency key as failed
                idempotency_service.update_idempotency_key(
                    db, idempotency_key, "failed", error_message=str(e)
                )
                logger.error(f"Customer creation failed: {e}")
                raise

    def update_customer(self, db: Session, customer_id: int, customer_update: customer_model.CustomerUpdate) -> Optional[CustomerInDB]:
        """Update customer using new repository interface (legacy method)"""
        updated_customer = customer_repo.update(db, customer_id, customer_update)
        if updated_customer:
            customer_data = updated_customer.model_dump()
            messaging.send_customer_event("customer_updated", customer_data)
        return updated_customer
    
    async def update_customer_with_integrity(
        self,
        db: Session,
        customer_id: int,
        customer_update: customer_model.CustomerUpdate,
        idempotency_key: str = None
    ) -> Optional[CustomerInDB]:
        """Update customer with data integrity protection"""
        await self.initialize()
        
        if not idempotency_key:
            idempotency_key = idempotency_service.generate_key(
                "update_customer", f"customer:{customer_id}"
            )
        
        # Use customer-based distributed lock
        async with customer_lock(customer_id, timeout=30):
            try:
                # Validate customer exists and is active
                existing_customer = customer_repo.get_by_id(db, customer_id)
                if not existing_customer:
                    raise ValueError(f"Customer {customer_id} not found")
                
                # Validate email uniqueness if email is being changed
                if customer_update.email != existing_customer.email:
                    await self._validate_email_uniqueness(db, customer_update.email, exclude_id=customer_id)
                
                # Create transaction context
                transaction_id = f"update_customer_{customer_id}_{uuid.uuid4().hex[:8]}"
                
                with CustomerTransactionContext(transaction_id) as tx_context:
                    updated_customer = None
                    original_data = existing_customer.model_dump()
                    
                    # Step 1: Update in database
                    def update_in_db():
                        nonlocal updated_customer
                        updated_customer = customer_repo.update(db, customer_id, customer_update)
                        return updated_customer
                    
                    def rollback_db_update():
                        if updated_customer:
                            # Restore original data
                            original_update = customer_model.CustomerUpdate(
                                name=original_data["name"],
                                email=original_data["email"]
                            )
                            customer_repo.update(db, customer_id, original_update)
                    
                    tx_context.add_local_db_step(
                        "update_customer_db",
                        update_in_db,
                        rollback_db_update
                    )
                    
                    # Step 2: Send update event
                    def send_update_event():
                        if updated_customer:
                            customer_data = updated_customer.model_dump()
                            messaging.send_customer_event("customer_updated", customer_data)
                        return True
                    
                    tx_context.add_integration_step(
                        "send_update_event",
                        send_update_event,
                        lambda: None  # Queue rollback handled by worker idempotency
                    )
                    
                    # Execute transaction
                    success = await tx_context.execute()
                    
                    if success and updated_customer:
                        logger.info(f"Customer updated successfully: {customer_id}")
                        return updated_customer
                    else:
                        raise RuntimeError("Customer update transaction failed")
                        
            except Exception as e:
                logger.error(f"Customer update failed: {e}")
                raise

    def delete_customer(self, db: Session, customer_id: int) -> bool:
        """Delete customer using new repository interface (legacy method)"""
        # Get customer data before deletion for event
        customer = customer_repo.get_by_id(db, customer_id)
        deleted = customer_repo.delete(db, customer_id)
        if deleted and customer:
            customer_data = customer.model_dump()
            messaging.send_customer_event("customer_deleted", customer_data)
        return deleted
    
    async def delete_customer_with_integrity(
        self,
        db: Session,
        customer_id: int,
        idempotency_key: str = None
    ) -> bool:
        """Delete customer with data integrity protection"""
        await self.initialize()
        
        if not idempotency_key:
            idempotency_key = idempotency_service.generate_key(
                "delete_customer", f"customer:{customer_id}"
            )
        
        # Use customer-based distributed lock
        async with customer_lock(customer_id, timeout=30):
            try:
                # Get customer data before deletion
                existing_customer = customer_repo.get_by_id(db, customer_id)
                if not existing_customer:
                    logger.warning(f"Customer {customer_id} not found for deletion")
                    return False
                
                # Create transaction context
                transaction_id = f"delete_customer_{customer_id}_{uuid.uuid4().hex[:8]}"
                
                with CustomerTransactionContext(transaction_id) as tx_context:
                    customer_data = existing_customer.model_dump()
                    
                    # Step 1: Soft delete in database
                    def delete_in_db():
                        success = customer_repo.delete(db, customer_id)
                        if success:
                            sync_service.update_sync_state(
                                db, customer_id, "stripe", sync_status="pending"
                            )
                        return success
                    
                    def rollback_delete():
                        # Reactivate the customer
                        customer_record = db.query(customer_model.Customer).filter(
                            customer_model.Customer.id == customer_id
                        ).first()
                        if customer_record:
                            customer_record.is_active = True
                            db.commit()
                    
                    tx_context.add_local_db_step(
                        "delete_customer_db",
                        delete_in_db,
                        rollback_delete
                    )
                    
                    # Step 2: Send delete event
                    def send_delete_event():
                        messaging.send_customer_event("customer_deleted", customer_data)
                        return True
                    
                    tx_context.add_integration_step(
                        "send_delete_event",
                        send_delete_event,
                        lambda: None
                    )
                    
                    # Execute transaction
                    success = await tx_context.execute()
                    
                    if success:
                        logger.info(f"Customer deleted successfully: {customer_id}")
                        return True
                    else:
                        raise RuntimeError("Customer deletion transaction failed")
                        
            except Exception as e:
                logger.error(f"Customer deletion failed: {e}")
                raise

    def get_customer(self, db: Session, customer_id: int) -> Optional[CustomerInDB]:
        """Get customer using new repository interface"""
        return customer_repo.get_by_id(db, customer_id)

    def get_all_customers(self, db: Session, skip: int = 0, limit: int = 100, filters: Dict[str, Any] = None) -> List[CustomerInDB]:
        """Get all customers with optional filtering"""
        return customer_repo.get_all(db, skip, limit, filters)
    
    def search_customers(self, db: Session, query: str) -> List[CustomerInDB]:
        """Search customers by name or email"""
        return customer_repo.search(db, query)
    
    # Convenience methods
    def get_customer_by_email(self, db: Session, email: str) -> Optional[CustomerInDB]:
        """Get customer by email"""
        return customer_repo.get_by_field(db, "email", email)
    
    def get_customer_by_stripe_id(self, db: Session, stripe_id: str) -> Optional[CustomerInDB]:
        """Get customer by Stripe ID"""
        return customer_repo.get_by_stripe_id(db, stripe_id)
    
    async def _validate_email_uniqueness(
        self,
        db: Session,
        email: str,
        exclude_id: int = None
    ):
        """Validate that email is unique among active customers"""
        # Check for active customers with this email
        query = db.query(customer_model.Customer).filter(
            customer_model.Customer.email == email,
            customer_model.Customer.is_active == True
        )
        
        if exclude_id:
            query = query.filter(customer_model.Customer.id != exclude_id)
        
        existing = query.first()
        if existing:
            raise ValueError(f"Email '{email}' is already taken by an active customer")
    
    def get_customer_sync_health(self, db: Session, customer_id: int) -> Dict[str, Any]:
        """Get sync health status for a customer across all integrations"""
        return sync_service.get_customer_sync_status(db, customer_id)
    
    def get_integration_health(self, db: Session, integration_name: str) -> Dict[str, Any]:
        """Get health statistics for an integration"""
        return sync_service.get_integration_health(db, integration_name)
    
    async def retry_failed_syncs(self, db: Session, integration_name: str = None) -> int:
        """Retry failed synchronizations"""
        failed_syncs = sync_service.get_failed_syncs(db, integration_name)
        retried_count = 0
        
        for failed_sync in failed_syncs:
            try:
                # Get customer data
                customer = customer_repo.get_by_id(db, failed_sync.customer_id)
                if customer:
                    # Send retry event
                    customer_data = customer.model_dump()
                    messaging.send_customer_event("customer_retry_sync", customer_data)
                    retried_count += 1
                    logger.info(f"Retrying sync for customer {customer.id}, integration: {failed_sync.integration_name}")
                
            except Exception as e:
                logger.error(f"Error retrying sync for customer {failed_sync.customer_id}: {e}")
        
        return retried_count
    
    def cleanup_orphaned_records(self, db: Session, integration_name: str = None) -> int:
        """Clean up orphaned integration records"""
        orphaned = sync_service.get_orphaned_records(db, integration_name)
        cleaned_count = 0
        
        for orphaned_sync in orphaned:
            try:
                # Get the integration service
                integration_service = integration_registry.get_integration(orphaned_sync.integration_name)
                if integration_service and orphaned_sync.external_id:
                    # Try to delete the external record
                    customer_data = {"stripe_customer_id": orphaned_sync.external_id}
                    success = integration_service.delete_customer(customer_data, db)
                    
                    if success:
                        sync_service.delete_sync_state(
                            db, orphaned_sync.customer_id, orphaned_sync.integration_name
                        )
                        cleaned_count += 1
                        logger.info(f"Cleaned up orphaned record: {orphaned_sync.external_id}")
                
            except Exception as e:
                logger.error(f"Error cleaning up orphaned record {orphaned_sync.external_id}: {e}")
        
        return cleaned_count


customer_service = CustomerService()