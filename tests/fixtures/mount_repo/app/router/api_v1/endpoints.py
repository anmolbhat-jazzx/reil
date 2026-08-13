from fastapi import APIRouter

from app.configuration.api import router as global_config_router
from app.widget.api import router as widget_router

api_v1 = APIRouter()
api_v1.include_router(global_config_router, prefix="/global-config")
api_v1.include_router(widget_router, prefix="/widgets")
