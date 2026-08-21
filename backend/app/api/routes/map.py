"""地图接口：直调 amap_service，不经过 agent。

供前端地图展示 / 调试使用。AmapError 不在此处理——
向上抛给 main.py 的全局异常处理器，统一转 502 + 信封。
"""

import logging

from fastapi import APIRouter, Query

from app.schemas.common import ApiResponse
from app.schemas.map import POIInfo, RouteInfo, RouteRequest, WeatherInfo
from app.services.amap_service import get_amap_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/map", tags=["map"])


@router.get("/poi", response_model=ApiResponse[list[POIInfo]])
async def search_poi(
    keywords: str = Query(..., min_length=1, description="搜索关键词"),
    city: str = Query(..., min_length=1, description="城市名"),
    limit: int = Query(default=10, ge=1, le=25, description="返回条数"),
) -> ApiResponse[list[POIInfo]]:
    """POI 关键词搜索。"""
    pois = await get_amap_service().search_poi(keywords, city, limit)
    logger.info("POI 搜索: keywords=%s city=%s 命中 %d 条", keywords, city, len(pois))
    return ApiResponse(success=True, message="ok", data=pois)


@router.get("/weather", response_model=ApiResponse[list[WeatherInfo]])
async def get_weather(city: str = Query(..., min_length=1, description="城市名")) -> ApiResponse[list[WeatherInfo]]:
    """未来几天天气预报（内部自动 城市名 → adcode）。"""
    forecasts = await get_amap_service().get_weather(city)
    logger.info("天气查询: city=%s 共 %d 天", city, len(forecasts))
    return ApiResponse(success=True, message="ok", data=forecasts)


@router.post("/route", response_model=ApiResponse[RouteInfo])
async def plan_route(payload: RouteRequest) -> ApiResponse[RouteInfo]:
    """两点间路线规划（内部自动 地址 → 坐标）。"""
    route = await get_amap_service().plan_route(
        origin_address=payload.origin,
        destination_address=payload.destination,
        mode=payload.mode,
        origin_city=payload.origin_city,
        destination_city=payload.destination_city,
    )
    return ApiResponse(success=True, message="ok", data=route)
