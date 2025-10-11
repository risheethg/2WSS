"""
Enhanced Database Transaction Management

This module provides robust transaction handling with:
- Nested transaction support via savepoints
- Automatic rollback on failures
- Deadlock detection and retry
- Connection timeout handling
- Transaction timeout monitoring
- Constraint violation handling
"""

import time
import random
import logging
from contextlib import contextmanager
from typing import Generator, Optional, Any, Callable, Dict, List
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy.orm import Session
from sqlalchemy.exc import (
    SQLAlchemyError,
    DisconnectionError,
    TimeoutError,
    OperationalError,
    IntegrityError,
    StatementError,
    InvalidRequestError,
    PendingRollbackError
)
from sqlalchemy import text

from .config import settings

logger = logging.getLogger(__name__)

class TransactionError(Exception):
    """Base exception for transaction-related errors."""
    pass

class DeadlockError(TransactionError):
    """Raised when a database deadlock is detected."""
    pass

class ConnectionTimeoutError(TransactionError):
    """Raised when database connection times out."""
    pass

class ConstraintViolationError(TransactionError):
    """Raised when database constraints are violated."""
    
    def __init__(self, constraint_type: str, message: str, original_error: Exception = None):
        self.constraint_type = constraint_type
        self.original_error = original_error
        super().__init__(message)

class TransactionIsolationLevel(Enum):
    """Database transaction isolation levels."""
    READ_UNCOMMITTED = "READ UNCOMMITTED"
    READ_COMMITTED = "READ COMMITTED"
    REPEATABLE_READ = "REPEATABLE READ"
    SERIALIZABLE = "SERIALIZABLE"

class DatabaseTransactionManager:
    """
    Comprehensive database transaction manager with advanced error handling.
    
    Features:
    - Automatic retry on transient errors
    - Deadlock detection and exponential backoff
    - Savepoint management for nested transactions
    - Connection timeout handling
    - Constraint violation classification
    - Transaction monitoring and logging
    """
    
    def __init__(self):
        self.max_retries = settings.DB_MAX_RETRIES
        self.base_delay = settings.DB_RETRY_BASE_DELAY
        self.max_delay = settings.DB_RETRY_MAX_DELAY
        self.deadlock_retries = settings.DB_DEADLOCK_RETRY_COUNT
    
    @contextmanager
    def transaction(
        self,
        db: Session,
        isolation_level: Optional[TransactionIsolationLevel] = None,
        timeout: Optional[int] = None,
        retry_on_deadlock: bool = True,
        savepoint_name: Optional[str] = None
    ) -> Generator[Session, None, None]:
        """
        Enhanced transaction context manager.
        
        Args:
            db: SQLAlchemy session
            isolation_level: Transaction isolation level
            timeout: Transaction timeout in seconds
            retry_on_deadlock: Whether to retry on deadlock
            savepoint_name: Name for nested transaction savepoint
        
        Yields:
            Session: Database session within transaction
        
        Raises:
            TransactionError: On transaction-related failures
            DeadlockError: On unresolvable deadlocks
            ConnectionTimeoutError: On connection timeouts
            ConstraintViolationError: On constraint violations
        """
        transaction_start = time.time()
        transaction_id = f"txn_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        
        logger.debug(f"Starting transaction {transaction_id}")
        
        # Set isolation level if specified
        if isolation_level:
            try:
                db.execute(text(f"SET TRANSACTION ISOLATION LEVEL {isolation_level.value}"))
                logger.debug(f"Set isolation level to {isolation_level.value}")
            except Exception as e:
                logger.warning(f"Failed to set isolation level: {e}")
        
        # Create savepoint for nested transactions
        savepoint = None
        if savepoint_name:
            try:
                savepoint = db.begin_nested()
                logger.debug(f"Created savepoint: {savepoint_name}")
            except Exception as e:
                logger.error(f"Failed to create savepoint {savepoint_name}: {e}")
                raise TransactionError(f"Could not create savepoint: {e}")
        
        try:
            # Set transaction timeout if specified
            if timeout:
                db.execute(text(f"SET statement_timeout = {timeout * 1000}"))  # PostgreSQL timeout in ms
            
            yield db
            
            # Commit savepoint or main transaction
            if savepoint:
                savepoint.commit()
                logger.debug(f"Committed savepoint: {savepoint_name}")
            else:
                db.commit()
                logger.debug(f"Committed transaction {transaction_id}")
            
        except Exception as e:
            transaction_duration = time.time() - transaction_start
            logger.error(f"Transaction {transaction_id} failed after {transaction_duration:.2f}s: {e}")
            
            try:
                # Rollback savepoint or main transaction
                if savepoint and not savepoint.is_active:
                    # Savepoint already rolled back
                    pass
                elif savepoint:
                    savepoint.rollback()
                    logger.debug(f"Rolled back savepoint: {savepoint_name}")
                else:
                    db.rollback()
                    logger.debug(f"Rolled back transaction {transaction_id}")
                    
            except Exception as rollback_error:
                logger.error(f"Failed to rollback transaction {transaction_id}: {rollback_error}")
                # Re-raise original error, not rollback error
            
            # Re-raise with enhanced error information
            self._handle_transaction_error(e, transaction_id, transaction_duration)
        
        finally:
            transaction_duration = time.time() - transaction_start
            logger.debug(f"Transaction {transaction_id} completed in {transaction_duration:.2f}s")
    
    def _handle_transaction_error(self, error: Exception, transaction_id: str, duration: float):
        """
        Classify and handle transaction errors.
        
        Args:
            error: Original exception
            transaction_id: Transaction identifier
            duration: Transaction duration in seconds
        
        Raises:
            Appropriate exception type based on error classification
        """
        error_msg = str(error).lower()
        
        # Deadlock detection
        if any(keyword in error_msg for keyword in ['deadlock', 'lock timeout', 'lock wait timeout']):
            raise DeadlockError(f"Database deadlock detected in {transaction_id}: {error}")
        
        # Connection timeout
        if any(keyword in error_msg for keyword in ['timeout', 'connection', 'network']):
            raise ConnectionTimeoutError(f"Database connection timeout in {transaction_id}: {error}")
        
        # Constraint violations
        if isinstance(error, IntegrityError):
            constraint_type = self._classify_constraint_violation(error)
            raise ConstraintViolationError(
                constraint_type=constraint_type,
                message=f"Database constraint violation ({constraint_type}) in {transaction_id}: {error}",
                original_error=error
            )
        
        # Connection issues
        if isinstance(error, (DisconnectionError, OperationalError)):
            if 'connection' in error_msg or 'network' in error_msg:
                raise ConnectionTimeoutError(f"Database connection error in {transaction_id}: {error}")
        
        # General transaction error
        raise TransactionError(f"Transaction failed in {transaction_id}: {error}")
    
    def _classify_constraint_violation(self, error: IntegrityError) -> str:
        """
        Classify the type of constraint violation.
        
        Args:
            error: IntegrityError instance
        
        Returns:
            String describing the constraint type
        """
        error_msg = str(error).lower()
        
        if 'unique' in error_msg or 'duplicate' in error_msg:
            return "unique_constraint"
        elif 'foreign key' in error_msg or 'fkey' in error_msg:
            return "foreign_key_constraint"
        elif 'not null' in error_msg or 'null value' in error_msg:
            return "not_null_constraint"
        elif 'check' in error_msg:
            return "check_constraint"
        else:
            return "unknown_constraint"
    
    def execute_with_retry(
        self,
        db: Session,
        operation: Callable[[Session], Any],
        max_retries: Optional[int] = None,
        retry_on_deadlock: bool = True,
        isolation_level: Optional[TransactionIsolationLevel] = None
    ) -> Any:
        """
        Execute database operation with automatic retry on transient failures.
        
        Args:
            db: SQLAlchemy session
            operation: Function to execute within transaction
            max_retries: Maximum retry attempts (None for default)
            retry_on_deadlock: Whether to retry on deadlocks
            isolation_level: Transaction isolation level
        
        Returns:
            Result of the operation
        
        Raises:
            Exception: After all retries exhausted
        """
        max_attempts = (max_retries or self.max_retries) + 1
        deadlock_attempts = self.deadlock_retries if retry_on_deadlock else 1
        
        last_error = None
        
        for attempt in range(max_attempts):
            try:
                with self.transaction(db, isolation_level=isolation_level):
                    result = operation(db)
                    return result
                    
            except DeadlockError as e:
                last_error = e
                if attempt < deadlock_attempts - 1:
                    # Exponential backoff with jitter for deadlocks
                    delay = min(
                        self.base_delay * (2 ** attempt) + random.uniform(0, 0.1),
                        self.max_delay
                    )
                    logger.warning(f"Deadlock detected, retrying in {delay:.2f}s (attempt {attempt + 1}/{deadlock_attempts})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Max deadlock retries exceeded: {e}")
                    raise
            
            except (ConnectionTimeoutError, OperationalError) as e:
                last_error = e
                if attempt < max_attempts - 1:
                    # Linear backoff for connection issues
                    delay = min(self.base_delay * (attempt + 1), self.max_delay)
                    logger.warning(f"Connection error, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_attempts})")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Max connection retries exceeded: {e}")
                    raise
            
            except ConstraintViolationError:
                # Don't retry constraint violations - they're business logic errors
                raise
            
            except Exception as e:
                last_error = e
                if attempt < max_attempts - 1:
                    delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                    logger.warning(f"Operation failed, retrying in {delay:.2f}s (attempt {attempt + 1}/{max_attempts}): {e}")
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Max retries exceeded: {e}")
                    raise
        
        # Should never reach here, but just in case
        raise last_error or TransactionError("Operation failed after all retries")

    @contextmanager
    def bulk_operation(self, db: Session, batch_size: int = 1000) -> Generator[Session, None, None]:
        """
        Context manager for bulk database operations with batching.
        
        Args:
            db: SQLAlchemy session
            batch_size: Number of operations per batch
        
        Yields:
            Session: Database session configured for bulk operations
        """
        logger.debug(f"Starting bulk operation with batch size {batch_size}")
        
        # Configure session for bulk operations
        original_autoflush = db.autoflush
        db.autoflush = False
        
        try:
            with self.transaction(db):
                yield db
                
        finally:
            # Restore original settings
            db.autoflush = original_autoflush
            logger.debug("Bulk operation completed")

# Global transaction manager instance
transaction_manager = DatabaseTransactionManager()