from fastapi import FastAPI

from app.router.api_v1.endpoints import api_v1

app = FastAPI()
app.include_router(api_v1, prefix="/api/v1")
