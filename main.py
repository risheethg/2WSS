from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio
from app.routes import customer_routes, webhook_routes, admin_routes
from app.core.database import initialize_database
from app.core.logger import logger

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info("Starting Zenskar Integration Service...")
    
    # Initialize database with enhanced connection management
    if initialize_database():
        logger.info("Database initialized successfully")
    else:
        logger.error("Database initialization failed")
        raise RuntimeError("Could not initialize database")
    
    # Start outbox processor in background
    from app.core.outbox_processor import outbox_processor
    outbox_task = asyncio.create_task(outbox_processor.start_background_processor())
    logger.info("Outbox processor started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Zenskar Integration Service...")
    
    # Stop outbox processor
    outbox_processor.stop_background_processor()
    outbox_task.cancel()
    try:
        await outbox_task
    except asyncio.CancelledError:
        pass
    outbox_processor.close()
    
    logger.info("Shutdown complete")

app = FastAPI(
    title="Zenskar Two-Way Integration Service",
    description="A service to manage and sync customer catalogs with enhanced data integrity and robust database management.",
    lifespan=lifespan
)

app.include_router(customer_routes.router)
app.include_router(webhook_routes.router)
app.include_router(admin_routes.router)



@app.get("/")
def read_root():
    return {"message": "Welcome to the Zenskar Assignment API"}