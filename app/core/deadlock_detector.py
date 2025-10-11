"""
Database Deadlock Detection and Recovery

This module provides specialized deadlock detection, analysis, and recovery mechanisms:
- Deadlock pattern detection
- Exponential backoff retry strategies  
- Deadlock prevention recommendations
- Monitoring and alerting for deadlock frequency
"""

import time
import random
import logging
import re
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass
from contextlib import contextmanager

from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError, DatabaseError
from sqlalchemy import text

from .config import settings

logger = logging.getLogger(__name__)

class DeadlockSeverity(Enum):
    """Severity levels for deadlock situations."""
    LOW = "low"          # Occasional deadlocks, normal operation
    MEDIUM = "medium"    # Moderate deadlock frequency
    HIGH = "high"        # High deadlock frequency, performance impact
    CRITICAL = "critical"  # Extremely high deadlock rate, system instability

@dataclass
class DeadlockEvent:
    """Information about a detected deadlock event."""
    timestamp: datetime
    session_id: Optional[str]
    transaction_duration: float
    retry_attempt: int
    error_message: str
    operation_context: Optional[str]
    recovery_action: str
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "transaction_duration": self.transaction_duration,
            "retry_attempt": self.retry_attempt,
            "error_message": self.error_message,
            "operation_context": self.operation_context,
            "recovery_action": self.recovery_action
        }

class DeadlockDetector:
    """
    Detects database deadlocks and provides recovery strategies.
    """
    
    def __init__(self):
        # Deadlock detection patterns for different databases
        self.deadlock_patterns = [
            r'deadlock detected',
            r'lock wait timeout',
            r'lock timeout',
            r'deadlock found when trying to get lock',
            r'transaction \(process id \d+\) was deadlocked',
            r'current transaction is aborted',
            r'serialization failure',
            r'could not serialize access'
        ]
        
        # Compile patterns for performance
        self.compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self.deadlock_patterns]
        
        # Deadlock tracking for monitoring
        self.deadlock_events: List[DeadlockEvent] = []
        self.max_events_history = 1000  # Keep last 1000 events
        
        # Configuration
        self.base_delay = settings.DB_RETRY_BASE_DELAY
        self.max_delay = settings.DB_RETRY_MAX_DELAY
        self.max_retries = settings.DB_DEADLOCK_RETRY_COUNT
    
    def is_deadlock_error(self, error: Exception) -> bool:
        """
        Check if an exception indicates a deadlock.
        
        Args:
            error: Exception to analyze
            
        Returns:
            bool: True if error indicates deadlock
        """
        error_message = str(error).lower()
        
        # Check against known deadlock patterns
        for pattern in self.compiled_patterns:
            if pattern.search(error_message):
                logger.debug(f"Deadlock detected by pattern: {pattern.pattern}")
                return True
        
        # Check specific exception types
        if isinstance(error, (OperationalError, DatabaseError)):
            # PostgreSQL specific error codes
            if hasattr(error, 'orig') and error.orig:
                if hasattr(error.orig, 'pgcode'):
                    # PostgreSQL deadlock error codes
                    deadlock_codes = ['40P01', '40001', '25P02']  # deadlock_detected, serialization_failure, etc.
                    if error.orig.pgcode in deadlock_codes:
                        logger.debug(f"Deadlock detected by PostgreSQL error code: {error.orig.pgcode}")
                        return True
        
        return False
    
    def calculate_retry_delay(self, attempt: int, jitter: bool = True) -> float:
        """
        Calculate delay for retry attempt using exponential backoff.
        
        Args:
            attempt: Current retry attempt number (0-based)
            jitter: Whether to add random jitter
            
        Returns:
            float: Delay in seconds
        """
        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay * (2 ** attempt)
        
        # Add jitter to prevent thundering herd
        if jitter:
            jitter_amount = delay * 0.1  # 10% jitter
            delay += random.uniform(-jitter_amount, jitter_amount)
        
        # Cap at maximum delay
        return min(delay, self.max_delay)
    
    def record_deadlock_event(
        self, 
        error: Exception,
        session_id: Optional[str] = None,
        transaction_duration: float = 0.0,
        retry_attempt: int = 0,
        operation_context: Optional[str] = None,
        recovery_action: str = "retry"
    ):
        """
        Record a deadlock event for monitoring and analysis.
        
        Args:
            error: The deadlock error
            session_id: Database session identifier
            transaction_duration: How long the transaction ran before deadlock
            retry_attempt: Which retry attempt this was
            operation_context: Context of the operation
            recovery_action: Action taken to recover
        """
        event = DeadlockEvent(
            timestamp=datetime.utcnow(),
            session_id=session_id,
            transaction_duration=transaction_duration,
            retry_attempt=retry_attempt,
            error_message=str(error),
            operation_context=operation_context,
            recovery_action=recovery_action
        )
        
        # Add to history (with size limit)
        self.deadlock_events.append(event)
        if len(self.deadlock_events) > self.max_events_history:
            self.deadlock_events.pop(0)
        
        # Log the event
        logger.warning(f"Deadlock event recorded: {event.to_dict()}")
        
        # Check if we need to alert on deadlock frequency
        self._check_deadlock_frequency_alert()
    
    def _check_deadlock_frequency_alert(self):
        """Check if deadlock frequency warrants an alert."""
        if len(self.deadlock_events) < 10:
            return
        
        # Check frequency in last hour
        one_hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent_deadlocks = [
            event for event in self.deadlock_events 
            if event.timestamp > one_hour_ago
        ]
        
        deadlock_count = len(recent_deadlocks)
        severity = self._assess_deadlock_severity(deadlock_count)
        
        if severity in [DeadlockSeverity.HIGH, DeadlockSeverity.CRITICAL]:
            logger.error(
                f"HIGH DEADLOCK FREQUENCY DETECTED: {deadlock_count} deadlocks in last hour. "
                f"Severity: {severity.value}. Investigate immediately!"
            )
    
    def _assess_deadlock_severity(self, deadlock_count_per_hour: int) -> DeadlockSeverity:
        """Assess the severity of deadlock frequency."""
        if deadlock_count_per_hour >= 100:
            return DeadlockSeverity.CRITICAL
        elif deadlock_count_per_hour >= 50:
            return DeadlockSeverity.HIGH
        elif deadlock_count_per_hour >= 20:
            return DeadlockSeverity.MEDIUM
        else:
            return DeadlockSeverity.LOW
    
    @contextmanager
    def deadlock_retry_context(
        self,
        db: Session,
        operation_context: Optional[str] = None,
        max_retries: Optional[int] = None
    ):
        """
        Context manager that automatically retries operations on deadlock.
        
        Args:
            db: Database session
            operation_context: Description of the operation
            max_retries: Maximum retry attempts (None for default)
        
        Yields:
            Session: Database session
        
        Raises:
            Exception: Original exception after all retries exhausted
        """
        max_attempts = (max_retries or self.max_retries)
        session_id = str(id(db))
        
        for attempt in range(max_attempts):
            transaction_start = time.time()
            
            try:
                yield db
                return  # Success, exit retry loop
                
            except Exception as e:
                transaction_duration = time.time() - transaction_start
                
                if self.is_deadlock_error(e):
                    # Record deadlock event
                    self.record_deadlock_event(
                        error=e,
                        session_id=session_id,
                        transaction_duration=transaction_duration,
                        retry_attempt=attempt,
                        operation_context=operation_context,
                        recovery_action=f"retry_{attempt + 1}"
                    )
                    
                    if attempt < max_attempts - 1:
                        # Calculate delay and retry
                        delay = self.calculate_retry_delay(attempt)
                        logger.warning(
                            f"Deadlock detected in {operation_context or 'unknown operation'}, "
                            f"retrying in {delay:.2f}s (attempt {attempt + 1}/{max_attempts})"
                        )
                        time.sleep(delay)
                        continue
                    else:
                        # Max retries exceeded
                        logger.error(
                            f"Max deadlock retries exceeded for {operation_context or 'unknown operation'} "
                            f"after {max_attempts} attempts"
                        )
                        self.record_deadlock_event(
                            error=e,
                            session_id=session_id,
                            transaction_duration=transaction_duration,
                            retry_attempt=attempt,
                            operation_context=operation_context,
                            recovery_action="failed_max_retries"
                        )
                        raise
                else:
                    # Not a deadlock, don't retry
                    raise
    
    def get_deadlock_statistics(self, hours: int = 24) -> Dict:
        """
        Get deadlock statistics for monitoring.
        
        Args:
            hours: Number of hours to analyze
            
        Returns:
            Dict: Deadlock statistics
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        recent_events = [
            event for event in self.deadlock_events 
            if event.timestamp > cutoff_time
        ]
        
        if not recent_events:
            return {
                "period_hours": hours,
                "total_deadlocks": 0,
                "deadlock_rate": 0.0,
                "severity": DeadlockSeverity.LOW.value,
                "avg_transaction_duration": 0.0,
                "operations_affected": [],
                "recovery_success_rate": 1.0
            }
        
        # Calculate statistics
        total_deadlocks = len(recent_events)
        deadlock_rate = total_deadlocks / hours  # per hour
        severity = self._assess_deadlock_severity(int(deadlock_rate))
        
        # Average transaction duration before deadlock
        avg_duration = sum(event.transaction_duration for event in recent_events) / len(recent_events)
        
        # Operations affected
        operations = set(event.operation_context for event in recent_events if event.operation_context)
        
        # Recovery success rate (events that led to successful retry vs failed)
        failed_recoveries = sum(1 for event in recent_events if event.recovery_action == "failed_max_retries")
        recovery_success_rate = (total_deadlocks - failed_recoveries) / total_deadlocks
        
        return {
            "period_hours": hours,
            "total_deadlocks": total_deadlocks,
            "deadlock_rate": deadlock_rate,
            "severity": severity.value,
            "avg_transaction_duration": avg_duration,
            "operations_affected": list(operations),
            "recovery_success_rate": recovery_success_rate,
            "last_deadlock": recent_events[-1].timestamp.isoformat() if recent_events else None
        }
    
    def get_deadlock_prevention_recommendations(self) -> List[str]:
        """
        Get recommendations for preventing deadlocks based on observed patterns.
        
        Returns:
            List[str]: List of prevention recommendations
        """
        recommendations = [
            "Always acquire locks in a consistent order across transactions",
            "Keep transactions short and avoid long-running operations",
            "Use appropriate isolation levels (avoid SERIALIZABLE unless necessary)",
            "Consider using SELECT ... FOR UPDATE NOWAIT to detect conflicts early",
            "Implement retry logic with exponential backoff for deadlock-prone operations",
            "Use connection pooling to reduce lock contention",
            "Consider partitioning large tables to reduce lock scope",
            "Avoid unnecessary locks by using appropriate query patterns"
        ]
        
        # Add specific recommendations based on observed patterns
        if len(self.deadlock_events) > 10:
            recent_events = self.deadlock_events[-50:]  # Last 50 events
            operations = [event.operation_context for event in recent_events if event.operation_context]
            
            if operations:
                most_common_operation = max(set(operations), key=operations.count)
                recommendations.append(
                    f"Pay special attention to '{most_common_operation}' operations - "
                    f"they account for many recent deadlocks"
                )
        
        return recommendations

# Global deadlock detector instance
deadlock_detector = DeadlockDetector()