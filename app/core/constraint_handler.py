"""
Database Constraint Violation Handler

This module provides specialized handling for different types of database constraints:
- Unique constraint violations
- Foreign key constraint violations  
- Not null constraint violations
- Check constraint violations

Features:
- Constraint type detection and classification
- Specific error messages for each constraint type
- Recovery suggestions and actions
- Logging and monitoring of constraint violations
"""

import re
import logging
from typing import Dict, Optional, Tuple, List
from datetime import datetime
from enum import Enum

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

class ConstraintType(Enum):
    """Types of database constraints."""
    UNIQUE = "unique"
    FOREIGN_KEY = "foreign_key"
    NOT_NULL = "not_null"
    CHECK = "check"
    UNKNOWN = "unknown"

class ConstraintViolationDetail:
    """Detailed information about a constraint violation."""
    
    def __init__(
        self,
        constraint_type: ConstraintType,
        table_name: Optional[str] = None,
        column_name: Optional[str] = None,
        constraint_name: Optional[str] = None,
        value: Optional[str] = None,
        message: str = "",
        recovery_suggestion: str = ""
    ):
        self.constraint_type = constraint_type
        self.table_name = table_name
        self.column_name = column_name
        self.constraint_name = constraint_name
        self.value = value
        self.message = message
        self.recovery_suggestion = recovery_suggestion
        self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for logging/serialization."""
        return {
            "constraint_type": self.constraint_type.value,
            "table_name": self.table_name,
            "column_name": self.column_name,
            "constraint_name": self.constraint_name,
            "value": self.value,
            "message": self.message,
            "recovery_suggestion": self.recovery_suggestion,
            "timestamp": self.timestamp.isoformat()
        }

class DatabaseConstraintHandler:
    """
    Handler for database constraint violations with detailed analysis and recovery suggestions.
    """
    
    def __init__(self):
        # Compile regex patterns for different database systems
        self.postgres_patterns = {
            ConstraintType.UNIQUE: [
                r'duplicate key value violates unique constraint "([^"]+)"',
                r'UNIQUE constraint failed: (\w+\.\w+)',
                r'Key \(([^)]+)\)=\([^)]+\) already exists'
            ],
            ConstraintType.FOREIGN_KEY: [
                r'violates foreign key constraint "([^"]+)"',
                r'FOREIGN KEY constraint failed',
                r'Key \(([^)]+)\)=\([^)]+\) is not present in table "([^"]+)"'
            ],
            ConstraintType.NOT_NULL: [
                r'null value in column "([^"]+)" violates not-null constraint',
                r'NOT NULL constraint failed: (\w+\.\w+)'
            ],
            ConstraintType.CHECK: [
                r'violates check constraint "([^"]+)"',
                r'CHECK constraint failed: ([^"]+)'
            ]
        }
        
        # Specific constraint mappings for the application
        self.application_constraints = {
            # Customer table constraints
            "customers_email_key": {
                "table": "customers",
                "column": "email",
                "type": ConstraintType.UNIQUE,
                "message": "A customer with this email address already exists",
                "recovery": "Use a different email address or update the existing customer"
            },
            "customers_stripe_customer_id_key": {
                "table": "customers", 
                "column": "stripe_customer_id",
                "type": ConstraintType.UNIQUE,
                "message": "This Stripe customer ID is already associated with another customer",
                "recovery": "Check if the customer already exists or use a different Stripe ID"
            },
            # Integration sync state constraints
            "integration_sync_states_customer_id_fkey": {
                "table": "integration_sync_states",
                "column": "customer_id",
                "type": ConstraintType.FOREIGN_KEY,
                "message": "Referenced customer does not exist",
                "recovery": "Ensure the customer exists before creating sync state"
            },
            "integration_sync_states_customer_integration_key": {
                "table": "integration_sync_states",
                "column": "customer_id, integration_name",
                "type": ConstraintType.UNIQUE,
                "message": "Sync state already exists for this customer and integration",
                "recovery": "Update the existing sync state instead of creating a new one"
            }
        }
    
    def parse_constraint_violation(self, error: IntegrityError) -> ConstraintViolationDetail:
        """
        Parse an IntegrityError and extract detailed constraint violation information.
        
        Args:
            error: SQLAlchemy IntegrityError
            
        Returns:
            ConstraintViolationDetail: Parsed constraint information
        """
        error_message = str(error.orig) if error.orig else str(error)
        error_lower = error_message.lower()
        
        logger.debug(f"Parsing constraint violation: {error_message}")
        
        # Try to match against known patterns
        for constraint_type, patterns in self.postgres_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, error_message, re.IGNORECASE)
                if match:
                    constraint_name = match.group(1) if match.groups() else None
                    
                    # Look up application-specific details
                    if constraint_name and constraint_name in self.application_constraints:
                        app_constraint = self.application_constraints[constraint_name]
                        return ConstraintViolationDetail(
                            constraint_type=app_constraint["type"],
                            table_name=app_constraint["table"],
                            column_name=app_constraint["column"],
                            constraint_name=constraint_name,
                            message=app_constraint["message"],
                            recovery_suggestion=app_constraint["recovery"]
                        )
                    
                    # Generic constraint info
                    return self._create_generic_constraint_detail(
                        constraint_type, constraint_name, error_message
                    )
        
        # Fallback: try to extract basic info
        return self._extract_fallback_info(error_message)
    
    def _create_generic_constraint_detail(
        self, 
        constraint_type: ConstraintType, 
        constraint_name: Optional[str],
        error_message: str
    ) -> ConstraintViolationDetail:
        """Create generic constraint detail when specific mapping not found."""
        
        messages = {
            ConstraintType.UNIQUE: "Duplicate value violates uniqueness requirement",
            ConstraintType.FOREIGN_KEY: "Referenced record does not exist",
            ConstraintType.NOT_NULL: "Required field cannot be empty",
            ConstraintType.CHECK: "Value does not meet validation requirements"
        }
        
        recovery_suggestions = {
            ConstraintType.UNIQUE: "Use a unique value or update the existing record",
            ConstraintType.FOREIGN_KEY: "Ensure the referenced record exists first",
            ConstraintType.NOT_NULL: "Provide a value for the required field",
            ConstraintType.CHECK: "Use a value that meets the validation criteria"
        }
        
        return ConstraintViolationDetail(
            constraint_type=constraint_type,
            constraint_name=constraint_name,
            message=messages.get(constraint_type, "Database constraint violation"),
            recovery_suggestion=recovery_suggestions.get(constraint_type, "Review and correct the data")
        )
    
    def _extract_fallback_info(self, error_message: str) -> ConstraintViolationDetail:
        """Extract basic info when pattern matching fails."""
        
        error_lower = error_message.lower()
        
        if any(word in error_lower for word in ['unique', 'duplicate']):
            constraint_type = ConstraintType.UNIQUE
        elif any(word in error_lower for word in ['foreign key', 'fkey']):
            constraint_type = ConstraintType.FOREIGN_KEY  
        elif any(word in error_lower for word in ['not null', 'null value']):
            constraint_type = ConstraintType.NOT_NULL
        elif 'check' in error_lower:
            constraint_type = ConstraintType.CHECK
        else:
            constraint_type = ConstraintType.UNKNOWN
        
        return ConstraintViolationDetail(
            constraint_type=constraint_type,
            message=f"Database constraint violation: {constraint_type.value}",
            recovery_suggestion="Review the data and operation requirements"
        )
    
    def handle_constraint_violation(
        self, 
        db: Session, 
        error: IntegrityError,
        operation_context: Optional[str] = None
    ) -> ConstraintViolationDetail:
        """
        Handle a constraint violation with logging and analysis.
        
        Args:
            db: Database session
            error: IntegrityError that occurred
            operation_context: Context of the operation (e.g., "customer_creation")
            
        Returns:
            ConstraintViolationDetail: Parsed constraint information
        """
        detail = self.parse_constraint_violation(error)
        
        # Log the constraint violation
        log_data = detail.to_dict()
        log_data['operation_context'] = operation_context
        
        logger.warning(f"Database constraint violation: {log_data}")
        
        # Record metrics (could integrate with monitoring system)
        self._record_constraint_violation_metric(detail, operation_context)
        
        return detail
    
    def _record_constraint_violation_metric(
        self, 
        detail: ConstraintViolationDetail, 
        operation_context: Optional[str]
    ):
        """Record constraint violation metrics for monitoring."""
        # This could integrate with Prometheus, StatsD, or other monitoring systems
        logger.info(
            f"METRIC constraint_violation "
            f"type={detail.constraint_type.value} "
            f"table={detail.table_name or 'unknown'} "
            f"column={detail.column_name or 'unknown'} "
            f"context={operation_context or 'unknown'}"
        )
    
    def get_constraint_violation_stats(self, db: Session) -> Dict:
        """
        Get statistics about constraint violations (if implemented with tracking).
        
        This could query a violations log table if you implement one.
        """
        # Placeholder for constraint violation statistics
        # In a full implementation, you might have a violations log table
        return {
            "total_violations_today": 0,
            "violation_types": {},
            "most_common_violations": [],
            "last_updated": datetime.utcnow().isoformat()
        }

# Global constraint handler instance
constraint_handler = DatabaseConstraintHandler()