"""日志配置。

全应用统一入口：setup_logging() 在 create_app() 时调用一次。
业务代码里只用 logging.getLogger(__name__)，不碰 handler 细节。
"""

import logging
import sys

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(level: str | None = None) -> None:
    """配置根 logger。

    level 缺省时读 settings.log_level（.env 的 LOG_LEVEL）。
    重复调用安全：先清空已有 handler，避免 uvicorn --reload 下日志翻倍。
    """
    from app.config import settings  # 延迟导入：避免日志模块与配置互相依赖

    resolved = (level or settings.log_level).upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))

    root = logging.getLogger()
    root.setLevel(resolved)
    root.handlers.clear()
    root.addHandler(handler)

    # 第三方库日志降噪：httpx 每次请求都打 DEBUG，吵且无用
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
