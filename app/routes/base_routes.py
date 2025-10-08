from fastapi import APIRouter

from ..core.response import response_handler 

 # ---Placholder---
base_router = APIRouter()

base_router.get("/")
async def test_route():
    return response_handler.success(message="Base route is working")