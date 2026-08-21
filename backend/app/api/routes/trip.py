"""旅行规划接口：agent 的唯一 HTTP 入口。

约定（与前端一致）：HTTP 永远 200，成败看信封里的 success。
agent 按契约本不抛异常（内部已 fallback），此处 try/except 是最后防线。
"""

import logging

from fastapi import APIRouter

from app.agent.trip_planner import get_trip_planner_agent
from app.schemas.trip import TripPlanResponse, TripRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trip", tags=["trip"])


@router.post("/plan", response_model=TripPlanResponse)
async def plan_trip(request: TripRequest) -> TripPlanResponse:
    """生成旅行计划。耗时可达 30s+（多轮工具调用），前端勿设短超时。"""
    logger.info(
        "收到规划请求: %s, %s ~ %s, 偏好=%s",
        request.city,
        request.start_date,
        request.end_date,
        request.preferences,
    )
    try:
        plan = await get_trip_planner_agent().plan(request)
    except Exception as exc:
        logger.exception("agent 违反契约抛出异常")
        return TripPlanResponse(success=False, message=f"行程规划失败: {exc}", data=None)
    logger.info("规划请求完成: %s, %d 天", plan.city, len(plan.days))
    return TripPlanResponse(success=True, message="行程规划成功", data=plan)
