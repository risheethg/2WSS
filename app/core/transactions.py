"""
Transaction Coordinator for managing distributed transactions and rollbacks

This service implements the Saga pattern to handle compensating transactions
when operations fail across multiple systems (local DB + external integrations).
"""

import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Awaitable
from enum import Enum
from sqlalchemy.orm import Session

from app.core.logger import logger


class TransactionStatus(Enum):
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


class StepStatus(Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    FAILED = "failed"
    COMPENSATED = "compensated"


@dataclass
class TransactionStep:
    """Represents a single step in a distributed transaction"""
    name: str
    execute_func: Callable
    compensate_func: Optional[Callable] = None
    execute_args: tuple = field(default_factory=tuple)
    execute_kwargs: dict = field(default_factory=dict)
    compensate_args: tuple = field(default_factory=tuple)
    compensate_kwargs: dict = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 3


@dataclass
class DistributedTransaction:
    """Represents a distributed transaction with multiple steps"""
    transaction_id: str
    steps: List[TransactionStep] = field(default_factory=list)
    status: TransactionStatus = TransactionStatus.PENDING
    current_step: int = 0
    completed_steps: List[int] = field(default_factory=list)
    failed_step: Optional[int] = None
    error: Optional[str] = None


class TransactionCoordinator:
    """Coordinates distributed transactions with compensating actions"""
    
    def __init__(self):
        self.active_transactions: Dict[str, DistributedTransaction] = {}
    
    def create_transaction(self, transaction_id: str) -> DistributedTransaction:
        """Create a new distributed transaction"""
        transaction = DistributedTransaction(transaction_id=transaction_id)
        self.active_transactions[transaction_id] = transaction
        logger.info(f"Created transaction: {transaction_id}")
        return transaction
    
    def add_step(
        self,
        transaction_id: str,
        name: str,
        execute_func: Callable,
        compensate_func: Optional[Callable] = None,
        execute_args: tuple = (),
        execute_kwargs: dict = None,
        compensate_args: tuple = (),
        compensate_kwargs: dict = None,
        max_retries: int = 3
    ) -> bool:
        """Add a step to the transaction"""
        if transaction_id not in self.active_transactions:
            logger.error(f"Transaction not found: {transaction_id}")
            return False
        
        execute_kwargs = execute_kwargs or {}
        compensate_kwargs = compensate_kwargs or {}
        
        step = TransactionStep(
            name=name,
            execute_func=execute_func,
            compensate_func=compensate_func,
            execute_args=execute_args,
            execute_kwargs=execute_kwargs,
            compensate_args=compensate_args,
            compensate_kwargs=compensate_kwargs,
            max_retries=max_retries
        )
        
        transaction = self.active_transactions[transaction_id]
        transaction.steps.append(step)
        logger.info(f"Added step '{name}' to transaction: {transaction_id}")
        return True
    
    async def execute_transaction(self, transaction_id: str) -> bool:
        """Execute all steps in the transaction"""
        if transaction_id not in self.active_transactions:
            logger.error(f"Transaction not found: {transaction_id}")
            return False
        
        transaction = self.active_transactions[transaction_id]
        transaction.status = TransactionStatus.EXECUTING
        
        try:
            logger.info(f"Executing transaction: {transaction_id}")
            
            # Execute each step
            for i, step in enumerate(transaction.steps):
                transaction.current_step = i
                success = await self._execute_step(transaction, step, i)
                
                if success:
                    transaction.completed_steps.append(i)
                    logger.info(f"Step '{step.name}' completed successfully")
                else:
                    # Step failed, initiate compensation
                    transaction.failed_step = i
                    transaction.status = TransactionStatus.FAILED
                    logger.error(f"Step '{step.name}' failed, starting compensation")
                    
                    compensation_success = await self._compensate_transaction(transaction)
                    if compensation_success:
                        transaction.status = TransactionStatus.COMPENSATED
                    
                    return False
            
            # All steps completed successfully
            transaction.status = TransactionStatus.COMPLETED
            logger.info(f"Transaction completed successfully: {transaction_id}")
            return True
            
        except Exception as e:
            transaction.error = str(e)
            transaction.status = TransactionStatus.FAILED
            logger.error(f"Transaction failed with exception: {transaction_id}, error: {e}")
            
            # Try to compensate
            try:
                await self._compensate_transaction(transaction)
                transaction.status = TransactionStatus.COMPENSATED
            except Exception as comp_e:
                logger.error(f"Compensation also failed for transaction {transaction_id}: {comp_e}")
            
            return False
        
        finally:
            # Clean up transaction (in production, you might want to keep this for audit)
            self.active_transactions.pop(transaction_id, None)
    
    async def _execute_step(self, transaction: DistributedTransaction, step: TransactionStep, step_index: int) -> bool:
        """Execute a single transaction step with retry logic"""
        while step.retries <= step.max_retries:
            try:
                logger.info(f"Executing step '{step.name}' (attempt {step.retries + 1})")
                
                # Call the step function
                if asyncio.iscoroutinefunction(step.execute_func):
                    result = await step.execute_func(*step.execute_args, **step.execute_kwargs)
                else:
                    result = step.execute_func(*step.execute_args, **step.execute_kwargs)
                
                step.result = result
                step.status = StepStatus.EXECUTED
                return True
                
            except Exception as e:
                step.retries += 1
                step.error = str(e)
                logger.warning(f"Step '{step.name}' failed (attempt {step.retries}): {e}")
                
                if step.retries > step.max_retries:
                    step.status = StepStatus.FAILED
                    logger.error(f"Step '{step.name}' failed after {step.max_retries} retries")
                    return False
                
                # Wait before retry (exponential backoff)
                await asyncio.sleep(min(2 ** step.retries, 30))
        
        return False
    
    async def _compensate_transaction(self, transaction: DistributedTransaction) -> bool:
        """Execute compensation for all completed steps in reverse order"""
        transaction.status = TransactionStatus.COMPENSATING
        logger.info(f"Starting compensation for transaction: {transaction.transaction_id}")
        
        compensation_success = True
        
        # Compensate completed steps in reverse order
        for step_index in reversed(transaction.completed_steps):
            step = transaction.steps[step_index]
            
            if step.compensate_func:
                try:
                    logger.info(f"Compensating step: {step.name}")
                    
                    if asyncio.iscoroutinefunction(step.compensate_func):
                        await step.compensate_func(*step.compensate_args, **step.compensate_kwargs)
                    else:
                        step.compensate_func(*step.compensate_args, **step.compensate_kwargs)
                    
                    step.status = StepStatus.COMPENSATED
                    logger.info(f"Successfully compensated step: {step.name}")
                    
                except Exception as e:
                    logger.error(f"Failed to compensate step '{step.name}': {e}")
                    compensation_success = False
            else:
                logger.warning(f"No compensation function for step: {step.name}")
        
        return compensation_success


# Global coordinator instance
transaction_coordinator = TransactionCoordinator()


class CustomerTransactionContext:
    """Context manager for customer-related distributed transactions"""
    
    def __init__(self, transaction_id: str):
        self.transaction_id = transaction_id
        self.transaction = None
    
    def __enter__(self):
        self.transaction = transaction_coordinator.create_transaction(self.transaction_id)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Clean up if transaction wasn't executed
        if self.transaction_id in transaction_coordinator.active_transactions:
            transaction_coordinator.active_transactions.pop(self.transaction_id)
    
    def add_local_db_step(self, name: str, func: Callable, compensate_func: Callable, *args, **kwargs):
        """Add a local database operation step"""
        return transaction_coordinator.add_step(
            self.transaction_id,
            name,
            func,
            compensate_func,
            args,
            kwargs,
            max_retries=1  # DB operations usually don't need many retries
        )
    
    def add_integration_step(self, name: str, func: Callable, compensate_func: Callable, *args, **kwargs):
        """Add an external integration step"""
        return transaction_coordinator.add_step(
            self.transaction_id,
            name,
            func,
            compensate_func,
            args,
            kwargs,
            max_retries=3  # External APIs might need more retries
        )
    
    async def execute(self) -> bool:
        """Execute the transaction"""
        return await transaction_coordinator.execute_transaction(self.transaction_id)


# Helper functions for common compensation patterns
def create_db_rollback(db: Session, table, record_id: int):
    """Create a database rollback function"""
    def rollback():
        try:
            record = db.query(table).filter(table.id == record_id).first()
            if record:
                db.delete(record)
                db.commit()
                logger.info(f"Rolled back database record: {table.__name__}:{record_id}")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to rollback database record {table.__name__}:{record_id}: {e}")
    
    return rollback


def create_integration_rollback(integration_service, operation: str, **params):
    """Create an integration rollback function"""
    def rollback():
        try:
            if operation == "delete_customer" and hasattr(integration_service, 'delete_customer'):
                integration_service.delete_customer(params['customer_data'], params['db'])
            elif operation == "create_customer" and hasattr(integration_service, 'create_customer'):
                # For create rollback, we typically want to delete
                integration_service.delete_customer(params['customer_data'], params['db'])
            logger.info(f"Rolled back integration operation: {operation}")
        except Exception as e:
            logger.error(f"Failed to rollback integration operation {operation}: {e}")
    
    return rollback