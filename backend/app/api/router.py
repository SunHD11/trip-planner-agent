"""聚合 /api 前缀下的所有子路由。

health 不在此列——它挂根路径（前端约定 GET /health）。
"""

from fastapi import APIRouter

from app.api.routes.map import router as map_router
from app.api.routes.trip import router as trip_router

api_router = APIRouter(prefix="/api")
api_router.include_router(map_router)
api_router.include_router(trip_router)
