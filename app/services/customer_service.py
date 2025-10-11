import asyncio
import uuid
from datetime import datetime
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from sqlalchemy.exc import IntegrityError, OperationalError, DatabaseError

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

# Import enhanced database management modules
from app.core.transaction_manager import (
    transaction_manager, 
    TransactionError, 
    DeadlockError, 
    ConnectionTimeoutError, 
    ConstraintViolationError,
    TransactionIsolationLevel
)
from app.core.constraint_handler import constraint_handler, ConstraintType
from app.core.deadlock_detector import deadlock_detector
from app.core.db_monitoring import db_monitor
from app.services.outbox_service import outbox_service

class CustomerService:
    def __init__(self):
        self.max_retries = 3
        self.base_delay = 1.0
    
    async def initialize(self):
        """Initialize the service and its dependencies"""
        if not lock_service._initialized:
            await lock_service.initialize()
    
    def create_customer(self, db: Session, customer: customer_model.CustomerCreate) -> CustomerInDB:
        """Create customer using transactional outbox pattern (legacy method enhanced)"""
        # Use transaction to ensure atomicity between customer creation and event publishing
        with transaction_manager.transaction(db):
            customer_in_db = customer_repo.create(db, customer)
            
            # Create outbox event within the same transaction
            # This guarantees the event is only created if customer creation succeeds
            outbox_service.create_event(
                db=db,
                event_type="customer_created",
                aggregate_id=str(customer_in_db.id),
                aggregate_type="customer", 
                payload=customer_in_db.model_dump(),
                partition_key=str(customer_in_db.id),  # Use customer ID for message ordering
                metadata={
                    "source": "customer_service",
                    "method": "create_customer_legacy",
                    "timestamp": datetime.utcnow().isoformat()
                }
            )
            
            return customer_in_db
    
    async def create_customer_with_integrity(
        self,
        db: Session,
        customer: customer_model.CustomerCreate,
        idempotency_key: str = None
    ) -> CustomerInDB:
        """
        Create customer with enhanced database integrity protection
        
        This method implements:
        - Email-based locking to prevent race conditions
        - Idempotency to prevent duplicate creations
        - Robust transaction management with deadlock recovery
        - Connection timeout handling
        - Constraint violation handling
        - Integration state tracking
        """
        await self.initialize()
        
        if not idempotency_key:
            idempotency_key = idempotency_service.generate_key(
                "create_customer", f"email:{customer.email}"
            )
        
        # Enhanced operation with database edge case handling
        def create_customer_operation(session: Session) -> CustomerInDB:
            """Database operation with comprehensive error handling."""
            
            # Check for duplicate request with constraint-aware logic
            is_duplicate, existing_key = idempotency_service.is_duplicate_request(
                session, idempotency_key, {"email": customer.email, "name": customer.name}
            )
            
            if is_duplicate and existing_key:
                if existing_key.status == "completed":
                    logger.info(f"Returning cached result for customer creation: {customer.email}")
                    return CustomerInDB(**existing_key.response_data["result"])
                elif existing_key.status == "processing":
                    raise ValueError("Customer creation already in progress")
            
            # Create idempotency key if not exists
            if not existing_key:
                idempotency_service.create_idempotency_key(
                    session, idempotency_key, "create_customer", 
                    {"email": customer.email, "name": customer.name}
                )
            
            # Validate email is not already taken (with soft-delete awareness)
            self._validate_email_uniqueness_sync(session, customer.email)
            
            # Create customer with constraint handling
            try:
                created_customer = customer_repo.create(session, customer)
                
                # Create sync state
                sync_service.create_sync_state(
                    session, created_customer.id, "stripe", sync_status="pending"
                )
                
                # Use transactional outbox pattern for reliable event publishing
                # This guarantees the event is only published if the transaction succeeds
                outbox_service.create_event(
                    db=session,
                    event_type="customer_created",
                    aggregate_id=str(created_customer.id),
                    aggregate_type="customer",
                    payload=created_customer.model_dump(),
                    partition_key=str(created_customer.id),  # Ensures message ordering
                    metadata={
                        "source": "customer_service",
                        "method": "create_customer_with_integrity",
                        "idempotency_key": idempotency_key,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                
                # Mark idempotency key as completed
                idempotency_service.update_idempotency_key(
                    session, idempotency_key, "completed", 
                    {"result": created_customer.model_dump()}
                )
                
                return created_customer
                
            except IntegrityError as e:
                # Enhanced constraint violation handling
                constraint_detail = constraint_handler.handle_constraint_violation(
                    session, e, "customer_creation"
                )
                
                if constraint_detail.constraint_type == ConstraintType.UNIQUE:
                    if "email" in (constraint_detail.column_name or ""):
                        raise ValueError(f"Customer with email {customer.email} already exists")
                    else:
                        raise ValueError(f"Duplicate value: {constraint_detail.message}")
                elif constraint_detail.constraint_type == ConstraintType.FOREIGN_KEY:
                    raise ValueError(f"Referenced record not found: {constraint_detail.message}")
                else:
                    raise ValueError(f"Data validation error: {constraint_detail.message}")
            
            except Exception as e:
                logger.error(f"Unexpected error in customer creation: {e}")
                raise
        
        # Use email-based distributed lock with enhanced transaction management
        async with email_lock(customer.email, timeout=30):
            try:
                # Execute with deadlock retry and connection timeout handling
                with deadlock_detector.deadlock_retry_context(
                    db, 
                    operation_context="customer_creation",
                    max_retries=3
                ):
                    result = transaction_manager.execute_with_retry(
                        db=db,
                        operation=create_customer_operation,
                        max_retries=3,
                        retry_on_deadlock=True,
                        isolation_level=TransactionIsolationLevel.READ_COMMITTED
                    )
                    
                    return result
                    
            except DeadlockError as e:
                logger.error(f"Customer creation failed due to deadlock: {e}")
                raise RuntimeError("Operation failed due to database contention. Please retry.")
            
            except ConnectionTimeoutError as e:
                db_monitor.record_connection_timeout()
                logger.error(f"Customer creation failed due to connection timeout: {e}")
                raise RuntimeError("Database connection timeout. Please retry.")
            
            except ConstraintViolationError as e:
                logger.warning(f"Customer creation failed due to constraint violation: {e}")
                if e.constraint_type == "unique_constraint":
                    raise ValueError("A customer with this information already exists")
                else:
                    raise ValueError(f"Data validation error: {e}")
            
            except TransactionError as e:
                logger.error(f"Customer creation transaction failed: {e}")
                raise RuntimeError("Database operation failed. Please retry.")
            
            except Exception as e:
                logger.error(f"Unexpected error in customer creation: {e}")
                raise

    def update_customer(self, db: Session, customer_id: int, customer_update: customer_model.CustomerUpdate) -> Optional[CustomerInDB]:
        """Update customer using transactional outbox pattern (legacy method enhanced)"""
        with transaction_manager.transaction(db):
            updated_customer = customer_repo.update(db, customer_id, customer_update)
            
            if updated_customer:
                # Create outbox event for update within the same transaction
                outbox_service.create_event(
                    db=db,
                    event_type="customer_updated",
                    aggregate_id=str(customer_id),
                    aggregate_type="customer",
                    payload=updated_customer.model_dump(),
                    partition_key=str(customer_id),  # Ensures message ordering
                    metadata={
                        "source": "customer_service", 
                        "method": "update_customer_legacy",
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                
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
        """Delete customer using transactional outbox pattern (legacy method enhanced)"""
        with transaction_manager.transaction(db):
            # Get customer data before deletion for event
            customer = customer_repo.get_by_id(db, customer_id)
            deleted = customer_repo.delete(db, customer_id)
            
            if deleted and customer:
                # Create outbox event for deletion within the same transaction
                outbox_service.create_event(
                    db=db,
                    event_type="customer_deleted",
                    aggregate_id=str(customer_id),
                    aggregate_type="customer",
                    payload=customer.model_dump(),
                    partition_key=str(customer_id),  # Ensures message ordering
                    metadata={
                        "source": "customer_service",
                        "method": "delete_customer_legacy", 
                        "timestamp": datetime.utcnow().isoformat()
                    }
                )
                
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
    
    def _validate_email_uniqueness_sync(
        self,
        db: Session,
        email: str,
        exclude_id: int = None
    ):
        """Synchronous email uniqueness validation for use within transactions"""
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
    
    async def _validate_email_uniqueness(
        self,
        db: Session,
        email: str,
        exclude_id: int = None
    ):
        """Validate that email is unique among active customers (async version)"""
        self._validate_email_uniqueness_sync(db, email, exclude_id)
    
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