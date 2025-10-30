from app.repos.base import repository_registry
from app.repos.customer_repo import customer_repo  
# from app.repos.invoice_repo import invoice_repo  # Uncomment when you need invoices


def setup_repositories():
    """
    Register all repository implementations.
    
    To add a new entity type:
    1. Create the repository class (copy existing pattern)
    2. Import it above
    3. Register it below
    4. Done!
    """
    
    # Register customer repository
    repository_registry.register("customers", customer_repo)
    
    # Register invoice repository when needed
    # repository_registry.register("invoices", invoice_repo)
    
    # Future entities can be added here:
    # from app.repos.product_repo import product_repo
    # repository_registry.register("products", product_repo)
    
    # from app.repos.order_repo import order_repo
    # repository_registry.register("orders", order_repo)


def get_available_entities() -> list:
    """Get list of all available entity types"""
    return list(repository_registry.get_all().keys())


# Initialize repositories when module is imported
setup_repositories()

# Export commonly used repositories
__all__ = ['customer_repo', 'repository_registry', 'setup_repositories']