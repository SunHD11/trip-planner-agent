"""FastAPI 应用入口。

启动：uv run uvicorn app.main:app --reload（或 uv run python -m app.main）

职责清单：
- 日志初始化（core/logging.py）
- CORS（来源白名单来自 .env 的 CORS_ORIGINS）
- lifespan：启动时预热 amap_service 单例（创建全局 httpx client），
  关闭时释放——避免连接泄漏
- 全局异常处理器：AmapError → 502 信封；未知异常 → 500 信封（不泄漏堆栈）
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.config import settings
from app.core.logging import setup_logging
from app.services.amap_service import AmapError, close_amap_service, get_amap_service

logger = logging.getLogger(__name__)

APP_TITLE = "智能旅行助手 API"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = (
    "基于单 Agent + 原生 function calling 的旅行规划服务。"
    "数据源：高德地图 Web 服务 API；模型：OpenAI 兼容接口。"
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动预热、关闭清理。"""
    get_amap_service()  # 预热单例：提前创建全局 httpx.AsyncClient
    logger.info("应用启动完成 (port=%d)", settings.port)
    yield
    await close_amap_service()
    logger.info("应用已关闭，HTTP 客户端已释放")


def _error_envelope(message: str) -> dict[str, object]:
    """统一错误信封，与 ApiResponse 结构一致。"""
    return {"success": False, "message": message, "data": None}


def create_app() -> FastAPI:
    """应用工厂：所有装配集中在此，测试可直接复用。"""
    setup_logging()

    app = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        description=APP_DESCRIPTION,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins_list(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)  # GET /health 挂根路径
    app.include_router(api_router)  # /api/map/*、/api/trip/*

    @app.exception_handler(AmapError)
    async def handle_amap_error(_: Request, exc: AmapError) -> JSONResponse:
        """高德业务错误 → 502 + 信封（上游服务故障语义）。"""
        logger.warning("高德服务错误: %s (infocode=%s)", exc.message, exc.info_code)
        return JSONResponse(status_code=502, content=_error_envelope(f"地图服务错误: {exc.message}"))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        """未知异常 → 500 + 信封。堆栈只进日志，不给前端。"""
        logger.exception("未处理异常: %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content=_error_envelope("服务器内部错误，请稍后重试"))

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
