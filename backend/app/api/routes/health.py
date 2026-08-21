"""健康检查（前端 api.ts 约定：GET /health → {status}）。"""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """存活探针：进程能响应即健康。"""
    return {"status": "healthy"}
