from fastapi import FastAPI
from app.routes import customer_routes, webhook_routes

app = FastAPI(
    title="Zenskar Two-Way Integration Service",
    description="A service to manage and sync customer catalogs with enhanced data integrity."
)

app.include_router(customer_routes.router)
app.include_router(webhook_routes.router)



@app.get("/")
def read_root():
    return {"message": "Welcome to the Zenskar Assignment API"}