from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.routes import customer_routes, webhook_routes, admin_routes, conflict_routes, reconciliation_routes, debug_routes
from app.services.reconciliation_scheduler import start_reconciliation_scheduler, stop_reconciliation_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await start_reconciliation_scheduler()
    yield
    # Shutdown
    await stop_reconciliation_scheduler()


app = FastAPI(
    title="Zenskar Two-Way Integration Service",
    description="A service to manage and sync customer catalogs.",
    lifespan=lifespan
)

app.include_router(customer_routes.router)
app.include_router(webhook_routes.router)
app.include_router(admin_routes.router)
#app.include_router(conflict_routes.router)
app.include_router(reconciliation_routes.router)
#app.include_router(debug_routes.router)



@app.get("/")
def read_root():
    return {"message": "Welcome to the Zenskar Assignment API"}