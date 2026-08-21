"""应用配置（pydantic-settings）。

相比 os.getenv 的优势：
- 类型化：字段带类型，环境变量自动转换（如 "60" → int 60）
- 启动即校验：必填项（LLM_API_KEY、AMAP_API_KEY 等）缺失或为空时，
  模块导入那一刻就抛 ValidationError，而不是运行到一半才崩
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/.env —— 用文件位置锚定路径，不受进程工作目录影响
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """全局配置。字段名与 .env 变量一一对应（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",  # .env 里的多余变量（如 UNSPLASH_*）不报错
        case_sensitive=False,
    )

    # ---- LLM（OpenAI 兼容接口，如 DeepSeek） ----
    llm_model_id: str = Field(..., min_length=1, description="模型名称")
    llm_api_key: str = Field(..., min_length=1, description="API 密钥")
    llm_base_url: str = Field(..., min_length=1, description="服务地址")
    llm_timeout: int = Field(default=60, gt=0, description="超时时间（秒）")

    # ---- 高德地图 ----
    amap_api_key: str = Field(..., min_length=1, description="高德 Web 服务 Key")

    # ---- 服务器 ----
    host: str = Field(default="0.0.0.0", description="监听地址")
    port: int = Field(default=8000, ge=1, le=65535, description="监听端口")
    log_level: str = Field(default="INFO", description="日志级别")
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        description="CORS 允许的来源（逗号分隔）",
    )

    def get_cors_origins_list(self) -> list[str]:
        """把逗号分隔的 CORS origins 字符串切成列表（去空白、去空项）。"""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


# 全局实例：导入本模块即完成 .env 读取与校验（缺密钥在此刻报错）
settings = Settings()


@lru_cache
def get_settings() -> Settings:
    """获取配置实例。供 FastAPI 依赖注入（Depends）与测试使用。"""
    return settings
