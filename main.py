from fastapi import FastAPI
from app.routes import customer_routes, webhook_routes, admin_routes, conflict_routes, test_routes

app = FastAPI(
    title="Zenskar Two-Way Integration Service",
    description="A service to manage and sync customer catalogs."
)

app.include_router(customer_routes.router)
app.include_router(webhook_routes.router)
app.include_router(admin_routes.router)
app.include_router(conflict_routes.router)
app.include_router(test_routes.router)



@app.get("/")
def read_root():
    return {"message": "Welcome to the Zenskar Assignment API"}