"""Agent 接口协议。

HTTP 层（routes/trip.py）只依赖本协议 + 工厂函数，
永远不直接 import 具体实现类——
这样 agent 内部无论怎么重构（换模型、换编排方式、拆多 agent），
路由代码一行都不用改。
"""

from typing import Protocol, runtime_checkable

from app.schemas.trip import TripPlan, TripRequest


@runtime_checkable
class TripPlannerAgent(Protocol):
    """旅行规划 Agent 的唯一契约：请求进，计划出。"""

    async def plan(self, request: TripRequest) -> TripPlan:
        """根据旅行请求生成旅行计划。

        约定：本方法不抛异常——任何失败（LLM 不可用、输出非法、循环超限）
        都返回结构合法的兜底计划，保证前端永远拿得到可渲染的数据。
        """
        ...
