"""
Idempotency Service for preventing duplicate operations

This service uses idempotency keys to ensure that operations can be safely retried
without causing duplicate effects. Critical for maintaining data consistency.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models.integrity import IdempotencyKey, IdempotencyKeyCreate, IdempotencyKeyInDB
from app.core.logger import logger


class IdempotencyService:
    """Service for managing idempotency keys"""
    
    @staticmethod
    def generate_key(operation_type: str, resource_identifier: str = None) -> str:
        """Generate a unique idempotency key"""
        if resource_identifier:
            return f"{operation_type}:{resource_identifier}:{uuid.uuid4().hex[:8]}"
        return f"{operation_type}:{uuid.uuid4().hex}"
    
    @staticmethod
    def hash_request(request_data: Dict[str, Any]) -> str:
        """Create a hash of the request data for comparison"""
        # Normalize the request data for consistent hashing
        normalized = json.dumps(request_data, sort_keys=True, default=str)
        return hashlib.sha256(normalized.encode()).hexdigest()
    
    @staticmethod
    def create_idempotency_key(
        db: Session,
        key: str,
        operation_type: str,
        request_data: Dict[str, Any],
        resource_id: str = None,
        expires_hours: int = 24
    ) -> IdempotencyKeyInDB:
        """Create a new idempotency key record"""
        try:
            request_hash = IdempotencyService.hash_request(request_data)
            expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
            
            db_key = IdempotencyKey(
                key=key,
                operation_type=operation_type,
                resource_id=resource_id,
                request_hash=request_hash,
                status="processing",
                expires_at=expires_at
            )
            
            db.add(db_key)
            db.commit()
            db.refresh(db_key)
            
            logger.info(f"Created idempotency key: {key}")
            return IdempotencyKeyInDB.from_orm(db_key)
            
        except IntegrityError:
            db.rollback()
            # Key already exists, fetch it
            existing = db.query(IdempotencyKey).filter(IdempotencyKey.key == key).first()
            if existing:
                return IdempotencyKeyInDB.from_orm(existing)
            raise
    
    @staticmethod
    def get_idempotency_key(db: Session, key: str) -> Optional[IdempotencyKeyInDB]:
        """Get an existing idempotency key"""
        db_key = db.query(IdempotencyKey).filter(IdempotencyKey.key == key).first()
        
        if db_key:
            # Check if key has expired
            if db_key.expires_at < datetime.utcnow():
                # Clean up expired key
                db.delete(db_key)
                db.commit()
                logger.info(f"Cleaned up expired idempotency key: {key}")
                return None
            
            return IdempotencyKeyInDB.from_orm(db_key)
        
        return None
    
    @staticmethod
    def update_idempotency_key(
        db: Session,
        key: str,
        status: str,
        response_data: Dict[str, Any] = None,
        error_message: str = None
    ) -> bool:
        """Update the status and response of an idempotency key"""
        try:
            db_key = db.query(IdempotencyKey).filter(IdempotencyKey.key == key).first()
            
            if not db_key:
                logger.warning(f"Idempotency key not found for update: {key}")
                return False
            
            db_key.status = status
            if response_data:
                db_key.response_data = response_data
            if error_message and status == "failed":
                if not db_key.response_data:
                    db_key.response_data = {}
                db_key.response_data["error"] = error_message
            
            db.commit()
            logger.info(f"Updated idempotency key {key} to status: {status}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating idempotency key {key}: {e}")
            return False
    
    @staticmethod
    def cleanup_expired_keys(db: Session) -> int:
        """Clean up expired idempotency keys"""
        try:
            expired_count = db.query(IdempotencyKey).filter(
                IdempotencyKey.expires_at < datetime.utcnow()
            ).delete()
            
            db.commit()
            
            if expired_count > 0:
                logger.info(f"Cleaned up {expired_count} expired idempotency keys")
            
            return expired_count
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error cleaning up expired idempotency keys: {e}")
            return 0
    
    @staticmethod
    def is_duplicate_request(
        db: Session,
        key: str,
        request_data: Dict[str, Any]
    ) -> Tuple[bool, Optional[IdempotencyKeyInDB]]:
        """
        Check if this is a duplicate request
        
        Returns:
            (is_duplicate, existing_key_record)
        """
        existing_key = IdempotencyService.get_idempotency_key(db, key)
        
        if not existing_key:
            return False, None
        
        # Check if the request data matches
        request_hash = IdempotencyService.hash_request(request_data)
        
        if existing_key.request_hash == request_hash:
            # This is a true duplicate (same key, same request)
            logger.info(f"Duplicate request detected for key: {key}")
            return True, existing_key
        else:
            # Same key but different request data - this is an error
            logger.warning(f"Idempotency key conflict: same key, different request data: {key}")
            return True, existing_key  # Still treat as duplicate to prevent conflicts


def with_idempotency(operation_type: str, expires_hours: int = 24):
    """
    Decorator for adding idempotency to functions
    
    Usage:
        @with_idempotency("create_customer")
        def create_customer_function(db, customer_data, idempotency_key=None):
            # function implementation
            pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Extract db session (assume it's the first argument)
            db = args[0] if args else kwargs.get('db')
            if not db:
                raise ValueError("Database session not found in function arguments")
            
            # Get or generate idempotency key
            idempotency_key = kwargs.pop('idempotency_key', None)
            if not idempotency_key:
                idempotency_key = IdempotencyService.generate_key(operation_type)
            
            # Extract request data for hashing (exclude db and idempotency_key)
            request_data = {k: v for k, v in kwargs.items() 
                          if k not in ['db', 'idempotency_key']}
            request_data.update({f'arg_{i}': arg for i, arg in enumerate(args[1:])})
            
            # Check for duplicate
            is_duplicate, existing_key = IdempotencyService.is_duplicate_request(
                db, idempotency_key, request_data
            )
            
            if is_duplicate and existing_key:
                if existing_key.status == "completed":
                    logger.info(f"Returning cached result for idempotency key: {idempotency_key}")
                    return existing_key.response_data
                elif existing_key.status == "processing":
                    logger.warning(f"Operation already in progress for key: {idempotency_key}")
                    raise ValueError("Operation already in progress")
                elif existing_key.status == "failed":
                    logger.info(f"Retrying failed operation for key: {idempotency_key}")
                    # Allow retry of failed operations
                    pass
            
            # Create idempotency key record
            if not existing_key:
                IdempotencyService.create_idempotency_key(
                    db, idempotency_key, operation_type, request_data, expires_hours=expires_hours
                )
            
            try:
                # Execute the function
                result = func(*args, **kwargs, idempotency_key=idempotency_key)
                
                # Mark as completed
                IdempotencyService.update_idempotency_key(
                    db, idempotency_key, "completed", {"result": result}
                )
                
                return result
                
            except Exception as e:
                # Mark as failed
                IdempotencyService.update_idempotency_key(
                    db, idempotency_key, "failed", error_message=str(e)
                )
                raise
        
        return wrapper
    return decorator


# Global service instance
idempotency_service = IdempotencyService()