from typing import Dict, List, Type
from app.integrations.base import BaseIntegrationService, OutwardIntegrationService, InwardIntegrationService
from app.integrations.stripe_service import StripeIntegration
from app.core.config import settings
from app.core.logger import logger


class IntegrationRegistry:
    """Manages all integration services."""
    
    def __init__(self):
        self._integrations: Dict[str, BaseIntegrationService] = {}
        self._initialized = False
    
    def register_integration(self, name: str, integration_class: Type[BaseIntegrationService], 
                           enabled: bool = True) -> None:
        """Register a new integration service."""
        try:
            integration_instance = integration_class(enabled=enabled)
            self._integrations[name] = integration_instance
            logger.info(f"Registered integration: {name}")
        except Exception as e:
            logger.error(f"Failed to register integration {name}: {e}")
    
    def initialize_integrations(self) -> None:
        """Initialize all registered integrations based on configuration."""
        if self._initialized:
            return
        
        # Register available integrations
        self.register_integration(
            "stripe", 
            StripeIntegration, 
            enabled=settings.STRIPE_INTEGRATION_ENABLED
        )
        
        # Sample registration for Salesforce (uncomment when implemented)
        # self.register_integration(
        #    "salesforce", 
        #    SalesforceIntegration, 
        #    enabled=getattr(settings, 'SALESFORCE_INTEGRATION_ENABLED', False)
        #)
        
        self._initialized = True
        logger.info(f"Integration registry initialized with {len(self._integrations)} integrations")
    
    def get_enabled_outward_integrations(self) -> List[OutwardIntegrationService]:
        """Get all enabled outward integration services."""
        if not self._initialized:
            self.initialize_integrations()
        
        enabled_integrations = []
        configured_integrations = settings.get_enabled_integrations()
        
        for name, integration in self._integrations.items():
            if (name in configured_integrations and 
                integration.is_enabled and 
                isinstance(integration, OutwardIntegrationService)):
                enabled_integrations.append(integration)
                logger.debug(f"Outward integration '{name}' is enabled")
        
        return enabled_integrations
    
    def get_enabled_inward_integrations(self) -> Dict[str, InwardIntegrationService]:
        """Get all enabled inward integration services."""
        if not self._initialized:
            self.initialize_integrations()
        
        enabled_integrations = {}
        configured_integrations = settings.get_enabled_integrations()
        
        for name, integration in self._integrations.items():
            if (name in configured_integrations and 
                integration.is_enabled and 
                isinstance(integration, InwardIntegrationService)):
                enabled_integrations[name] = integration
                logger.debug(f"Inward integration '{name}' is enabled")
        
        return enabled_integrations
    
    def get_integration(self, name: str) -> BaseIntegrationService:
        """Get integration by name."""
        if not self._initialized:
            self.initialize_integrations()
        
        return self._integrations.get(name)
    
    def is_integration_enabled(self, name: str) -> bool:
        """Check if integration is enabled."""
        integration = self.get_integration(name)
        return integration is not None and integration.is_enabled
    
    def list_integrations(self) -> Dict[str, Dict[str, any]]:
        """List all registered integrations and their status."""
        if not self._initialized:
            self.initialize_integrations()
        
        return {
            name: {
                "enabled": integration.is_enabled,
                "outward_sync": isinstance(integration, OutwardIntegrationService),
                "inward_sync": isinstance(integration, InwardIntegrationService),
                "class": integration.__class__.__name__
            }
            for name, integration in self._integrations.items()
        }


# Global registry instance
integration_registry = IntegrationRegistry()