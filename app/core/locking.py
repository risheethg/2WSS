"""
Distributed Locking Service to prevent race conditions

This service provides Redis-based distributed locks to ensure that only one process
can modify a customer record at a time, preventing race conditions between
webhook processing and API operations.
"""

import asyncio
import time
import uuid
from typing import Optional, AsyncContextManager
from contextlib import asynccontextmanager
import redis.asyncio as redis
from app.core.config import settings
from app.core.logger import logger


class DistributedLock:
    """Redis-based distributed lock implementation"""
    
    def __init__(self, redis_client, key: str, timeout: int = 30, blocking_timeout: int = 10):
        self.redis = redis_client
        self.key = f"lock:{key}"
        self.timeout = timeout  # Lock expiration time
        self.blocking_timeout = blocking_timeout  # Max time to wait for lock
        self.identifier = str(uuid.uuid4())
        self.locked = False
        
    async def acquire(self) -> bool:
        """Acquire the distributed lock"""
        end_time = time.time() + self.blocking_timeout
        
        while time.time() < end_time:
            # Try to acquire lock with expiration
            result = await self.redis.set(
                self.key, 
                self.identifier, 
                nx=True,  # Only set if key doesn't exist
                ex=self.timeout  # Expiration time
            )
            
            if result:
                self.locked = True
                logger.debug(f"Acquired lock: {self.key}")
                return True
            
            # Wait a bit before retrying
            await asyncio.sleep(0.1)
        
        logger.warning(f"Failed to acquire lock: {self.key} after {self.blocking_timeout}s")
        return False
    
    async def release(self) -> bool:
        """Release the distributed lock"""
        if not self.locked:
            return False
        
        # Lua script to ensure we only delete our own lock
        lua_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
        """
        
        try:
            result = await self.redis.eval(lua_script, 1, self.key, self.identifier)
            if result:
                self.locked = False
                logger.debug(f"Released lock: {self.key}")
                return True
            else:
                logger.warning(f"Lock was already released or expired: {self.key}")
                return False
        except Exception as e:
            logger.error(f"Error releasing lock {self.key}: {e}")
            return False
    
    async def __aenter__(self):
        """Async context manager entry"""
        success = await self.acquire()
        if not success:
            raise RuntimeError(f"Failed to acquire lock: {self.key}")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.release()


class LockService:
    """Service for managing distributed locks"""
    
    def __init__(self):
        self.redis_client: Optional[redis.Redis] = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize Redis connection"""
        try:
            # For now, we'll use a simple in-memory fallback if Redis isn't available
            # In production, you'd want to configure Redis properly
            redis_url = getattr(settings, 'REDIS_URL', 'redis://localhost:6379')
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            
            # Test connection
            await self.redis_client.ping()
            self._initialized = True
            logger.info("Redis connection established for distributed locking")
            
        except Exception as e:
            logger.warning(f"Redis not available, using in-memory locks: {e}")
            # Fallback to simple in-memory dict for development
            self.redis_client = InMemoryRedis()
            self._initialized = True
    
    def get_customer_lock(self, customer_id: int, timeout: int = 30) -> DistributedLock:
        """Get a distributed lock for a specific customer"""
        if not self._initialized:
            raise RuntimeError("LockService not initialized. Call initialize() first.")
        
        return DistributedLock(
            self.redis_client,
            f"customer:{customer_id}",
            timeout=timeout
        )
    
    def get_email_lock(self, email: str, timeout: int = 30) -> DistributedLock:
        """Get a distributed lock for a specific email"""
        if not self._initialized:
            raise RuntimeError("LockService not initialized. Call initialize() first.")
        
        # Normalize email for consistent locking
        normalized_email = email.lower().strip()
        return DistributedLock(
            self.redis_client,
            f"email:{normalized_email}",
            timeout=timeout
        )
    
    def get_integration_lock(self, integration_name: str, external_id: str, timeout: int = 30) -> DistributedLock:
        """Get a distributed lock for a specific integration record"""
        if not self._initialized:
            raise RuntimeError("LockService not initialized. Call initialize() first.")
        
        return DistributedLock(
            self.redis_client,
            f"integration:{integration_name}:{external_id}",
            timeout=timeout
        )


class InMemoryRedis:
    """Simple in-memory Redis mock for development/testing"""
    
    def __init__(self):
        self._data = {}
        self._expiry = {}
    
    async def set(self, key: str, value: str, nx: bool = False, ex: int = None) -> bool:
        """Mock Redis SET command"""
        current_time = time.time()
        
        # Clean up expired keys
        expired_keys = [k for k, exp_time in self._expiry.items() if exp_time < current_time]
        for k in expired_keys:
            self._data.pop(k, None)
            self._expiry.pop(k, None)
        
        # Check if key exists and nx=True
        if nx and key in self._data:
            return False
        
        # Set the value
        self._data[key] = value
        if ex:
            self._expiry[key] = current_time + ex
        
        return True
    
    async def eval(self, script: str, num_keys: int, key: str, identifier: str):
        """Mock Redis EVAL command for lock release"""
        if self._data.get(key) == identifier:
            self._data.pop(key, None)
            self._expiry.pop(key, None)
            return 1
        return 0
    
    async def ping(self):
        """Mock Redis PING command"""
        return "PONG"


# Global lock service instance
lock_service = LockService()


@asynccontextmanager
async def customer_lock(customer_id: int, timeout: int = 30) -> AsyncContextManager[None]:
    """Async context manager for customer locking"""
    if not lock_service._initialized:
        await lock_service.initialize()
    
    lock = lock_service.get_customer_lock(customer_id, timeout)
    async with lock:
        yield


@asynccontextmanager 
async def email_lock(email: str, timeout: int = 30) -> AsyncContextManager[None]:
    """Async context manager for email locking"""
    if not lock_service._initialized:
        await lock_service.initialize()
    
    lock = lock_service.get_email_lock(email, timeout)
    async with lock:
        yield


@asynccontextmanager
async def integration_lock(integration_name: str, external_id: str, timeout: int = 30) -> AsyncContextManager[None]:
    """Async context manager for integration locking"""
    if not lock_service._initialized:
        await lock_service.initialize()
    
    lock = lock_service.get_integration_lock(integration_name, external_id, timeout)
    async with lock:
        yield