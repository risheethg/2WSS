from fastapi import FastAPI
from app.routes import customer_routes

app = FastAPI(
    title="Zenskar Integration Service",
    description="A service to manage and sync customer catalogs.",
    version="1.0.0"
)

app.include_router(customer_routes.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Zenskar Assignment API"}