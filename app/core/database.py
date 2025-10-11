from sqlalchemy import create_engine, MetaData, event, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import (
    SQLAlchemyError, 
    DisconnectionError, 
    TimeoutError,
    OperationalError,
    IntegrityError,
    StatementError
)
from sqlalchemy.pool import QueuePool
import time
import logging
import asyncio
from contextlib import contextmanager
from typing import Generator, Optional, Any, Dict
from datetime import datetime, timedelta

from .config import settings

logger = logging.getLogger(__name__)

# Enhanced database engine with robust connection pool
def create_database_engine():
    """Create SQLAlchemy engine with robust connection pool configuration."""
    
    # Parse database URL to add connection parameters
    database_url = settings.DATABASE_URL
    
    # Add connection pool parameters for PostgreSQL
    if database_url.startswith('postgresql'):
        connect_args = {
            "connect_timeout": settings.DB_CONNECT_TIMEOUT,
            "command_timeout": settings.DB_COMMAND_TIMEOUT,
            "application_name": "zenskar_api"
        }
    else:
        connect_args = {}
    
    engine = create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=settings.DB_POOL_PRE_PING,
        connect_args=connect_args,
        echo=False,  # Set to True for SQL debugging
        # Connection validation
        pool_reset_on_return='commit'
    )
    
    # Add connection event listeners for monitoring
    @event.listens_for(engine, "connect")
    def receive_connect(dbapi_connection, connection_record):
        """Log successful connections."""
        logger.debug("Database connection established")
        connection_record.info['connect_time'] = datetime.utcnow()
    
    @event.listens_for(engine, "checkout")
    def receive_checkout(dbapi_connection, connection_record, connection_proxy):
        """Log connection checkout from pool."""
        logger.debug("Connection checked out from pool")
    
    @event.listens_for(engine, "checkin")
    def receive_checkin(dbapi_connection, connection_record):
        """Log connection checkin to pool."""
        logger.debug("Connection returned to pool")
    
    @event.listens_for(engine, "invalidate")
    def receive_invalidate(dbapi_connection, connection_record, exception):
        """Log connection invalidation."""
        logger.warning(f"Connection invalidated: {exception}")
    
    return engine

# Create database engine
engine = create_database_engine()

# Enhanced sessionmaker
SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=engine,
    expire_on_commit=False  # Keep objects accessible after commit
)

# Create base class for models
Base = declarative_base()

class DatabaseHealthChecker:
    """Monitor database connection health and pool status."""
    
    @staticmethod
    def check_connection_health() -> Dict[str, Any]:
        """Check database connection health and return status."""
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT 1"))
                result.fetchone()
                
                # Get pool status
                pool = engine.pool
                
                return {
                    "status": "healthy",
                    "timestamp": datetime.utcnow().isoformat(),
                    "pool_size": pool.size(),
                    "checked_in": pool.checkedin(),
                    "checked_out": pool.checkedout(),
                    "overflow": pool.overflow(),
                    "invalid": pool.invalid()
                }
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    @staticmethod
    def get_pool_status() -> Dict[str, int]:
        """Get detailed connection pool status."""
        pool = engine.pool
        return {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "invalid": pool.invalid()
        }

# Enhanced database dependency with session management
def get_db() -> Generator[Session, None, None]:
    """
    Enhanced database session dependency with proper error handling.
    
    Features:
    - Automatic session cleanup
    - Connection validation
    - Error logging
    - Session timeout handling
    """
    db = None
    session_start = time.time()
    
    try:
        db = SessionLocal()
        
        # Set session info for monitoring
        db.info = {
            'created_at': datetime.utcnow(),
            'session_id': id(db)
        }
        
        logger.debug(f"Database session created: {id(db)}")
        
        yield db
        
    except Exception as e:
        if db:
            logger.error(f"Database session error: {e}")
            try:
                db.rollback()
                logger.debug("Database session rolled back due to error")
            except Exception as rollback_error:
                logger.error(f"Failed to rollback session: {rollback_error}")
        raise
    finally:
        if db:
            session_duration = time.time() - session_start
            
            # Check for long-running sessions
            if session_duration > settings.DB_SESSION_TIMEOUT:
                logger.warning(f"Long-running session detected: {session_duration:.2f}s")
            
            try:
                db.close()
                logger.debug(f"Database session closed: {id(db)} (duration: {session_duration:.2f}s)")
            except Exception as close_error:
                logger.error(f"Error closing database session: {close_error}")

@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions outside of FastAPI dependency injection.
    
    Use this for background tasks, utilities, or any non-request contexts.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error in context manager: {e}")
        db.rollback()
        raise
    finally:
        db.close()

# Create all tables
def create_tables():
    """Create all database tables with error handling."""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        raise

# Database initialization and health check
def initialize_database():
    """Initialize database and perform health checks."""
    try:
        # Check if database is accessible
        health_status = DatabaseHealthChecker.check_connection_health()
        
        if health_status["status"] == "healthy":
            logger.info("Database connection established successfully")
            logger.info(f"Connection pool status: {health_status}")
            
            # Create tables if needed
            create_tables()
            
            return True
        else:
            logger.error(f"Database health check failed: {health_status}")
            return False
            
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False