"""
Base classes for third-party integrations.
"""

from abc import ABC, abstractmethod
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional


class OutwardIntegrationService(ABC):
    """Sync data from our app to external services."""

    @abstractmethod
    def create_customer(self, customer_data: dict, db: Session) -> Optional[Dict[str, Any]]:
        """Create customer in external service."""
        pass

    @abstractmethod
    def update_customer(self, customer_data: dict, db: Session) -> bool:
        """Update customer in external service."""
        pass

    @abstractmethod
    def delete_customer(self, customer_data: dict, db: Session) -> bool:
        """Delete customer in external service."""
        pass


class InwardIntegrationService(ABC):
    """Handle incoming data from external services."""

    @abstractmethod
    def handle_webhook_event(self, event_type: str, payload: dict, db: Session) -> bool:
        """Process webhook event from external service."""
        pass

    @abstractmethod
    def verify_webhook_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        """Verify webhook signature for security."""
        pass


class BaseIntegrationService(OutwardIntegrationService, InwardIntegrationService):
    """Base class for bidirectional integrations."""

    def __init__(self, name: str, enabled: bool = True):
        self.name = name
        self.enabled = enabled
        print(f"{self.name.title()} Integration {'Enabled' if enabled else 'Disabled'}.")

    @property
    def is_enabled(self) -> bool:
        return self.enabled

    def enable(self) -> None:
        self.enabled = True
        print(f"{self.name.title()} Integration Enabled.")

    def disable(self) -> None:
        self.enabled = False
        print(f"{self.name.title()} Integration Disabled.")