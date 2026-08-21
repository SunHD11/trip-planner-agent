"""单 Agent 旅行规划器：原生 function calling 循环。

核心流程（详见 docs/IMPLEMENTATION_GUIDE.md Step 8）：
1. 组装 [system, user] 消息
2. 循环 ≤ MAX_ITERATIONS 轮：LLM 决定调工具 → 执行 → 结果回填；
   直到某轮响应不含 tool_calls，即得到最终 JSON 文本
3. 提取 JSON（三级策略）→ pydantic 校验 → 失败让 LLM 修正重试 1 次
4. 仍失败或循环耗尽 → 兜底计划（保证前端永远拿到合法结构）

本模块只导入 TOOL_REGISTRY / TOOL_SCHEMAS，不关心工具内部实现。
"""

import json
import logging
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError

from app.agent.base import TripPlannerAgent
from app.agent.prompts.trip_planner import (
    TRIP_PLANNER_SYSTEM_PROMPT,
    build_user_message,
)
from app.agent.tools.amap_tools import TOOL_REGISTRY, TOOL_SCHEMAS
from app.core.llm import LLM, LLMError
from app.schemas.trip import (
    Attraction,
    DayPlan,
    Meal,
    TripPlan,
    TripRequest,
    calc_travel_days,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10  # 工具循环硬上限，防止模型死循环烧 token
JSON_RETRY_LIMIT = 1  # JSON 校验失败后让 LLM 修正的次数


class JsonExtractionError(ValueError):
    """LLM 回复中提取不到合法 JSON 对象。"""


# ============ JSON 提取与错误格式化 ============


def extract_json(text: str) -> dict[str, Any]:
    """从 LLM 回复中提取 JSON 对象。

    三级策略：```json 围栏 → 普通 ``` 围栏 → 最外层花括号子串。
    """
    if not text:
        raise JsonExtractionError("LLM 回复为空")

    candidate: str | None
    if "```json" in text:
        start = text.find("```json") + len("```json")
        end = text.find("```", start)
        candidate = text[start:end] if end != -1 else text[start:]
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        candidate = text[start:end] if end != -1 else text[start:]
    else:
        first, last = text.find("{"), text.rfind("}")
        candidate = text[first : last + 1] if first != -1 and last > first else None

    if candidate is None:
        raise JsonExtractionError("回复中未找到 JSON 内容")
    try:
        data = json.loads(candidate.strip())
    except json.JSONDecodeError as exc:
        raise JsonExtractionError(f"JSON 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise JsonExtractionError("提取到的 JSON 不是对象")
    return data


def _format_validation_error(exc: Exception) -> str:
    """把校验/提取错误压缩成给 LLM 看的可读文本（截断防爆 token）。"""
    text = str(exc)
    return text[:800] if len(text) > 800 else text


def _assistant_message_to_dict(message: Any) -> dict[str, Any]:
    """把 SDK 的 assistant message 转成最小化 dict 回填对话。

    只保留 role/content/tool_calls 三个键——
    不同 LLM 提供商对多余字段的容忍度不同，最小化最稳。
    """
    payload: dict[str, Any] = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
            for call in message.tool_calls
        ]
    return payload


# ============ 兜底计划 ============


def _create_fallback_plan(request: TripRequest) -> TripPlan:
    """兜底计划：LLM 不可用、输出非法或循环超限时，保证前端有合法数据可渲染。"""
    travel_days = calc_travel_days(request.start_date, request.end_date)
    start = date.fromisoformat(request.start_date)
    days = [
        DayPlan(
            date=(start + timedelta(days=i)).isoformat(),
            day_index=i,
            description=f"第{i + 1}天行程框架（智能规划暂不可用，请自行安排{request.city}行程）",
            transportation=request.transportation,
            accommodation=request.accommodation,
            attractions=[
                Attraction(
                    name=f"{request.city}热门景点{j + 1}",
                    description="占位景点，请以实际景区信息为准",
                )
                for j in range(2)
            ],
            meals=[
                Meal(type="breakfast", name="当地早餐", description="推荐品尝当地特色早餐"),
                Meal(type="lunch", name="当地午餐", description="推荐品尝当地特色午餐"),
                Meal(type="dinner", name="当地晚餐", description="推荐品尝当地特色晚餐"),
            ],
        )
        for i in range(travel_days)
    ]
    return TripPlan(
        city=request.city,
        start_date=request.start_date,
        end_date=request.end_date,
        days=days,
        overall_suggestions="智能规划暂时不可用，已生成基础行程框架。建议提前查询各景点开放时间。",
    )


# ============ Agent 实现 ============


class SimpleTripPlannerAgent:
    """单 Agent + 原生 function calling 的旅行规划器。"""

    def __init__(self, llm: LLM | None = None) -> None:
        self._llm = llm or LLM()

    async def plan(self, request: TripRequest) -> TripPlan:
        """生成旅行计划。永不抛异常：任何失败都退化为兜底计划。"""
        try:
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": TRIP_PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": build_user_message(request)},
            ]
            final_content = await self._run_tool_loop(messages)
            if final_content is None:
                logger.warning("工具循环 %d 轮未得到最终答案，使用兜底计划", MAX_ITERATIONS)
                return _create_fallback_plan(request)
            plan = await self._parse_and_validate(messages, final_content)
            if plan is not None:
                logger.info("旅行计划生成成功: %s, %d 天", plan.city, len(plan.days))
                return plan
            return _create_fallback_plan(request)
        except LLMError:
            logger.exception("LLM 调用失败，使用兜底计划")
            return _create_fallback_plan(request)
        except Exception:
            logger.exception("Agent 未预期异常，使用兜底计划")
            return _create_fallback_plan(request)

    async def _run_tool_loop(self, messages: list[dict[str, Any]]) -> str | None:
        """执行 tool-calling 循环。返回最终文本；超过轮数上限返回 None。"""
        for iteration in range(1, MAX_ITERATIONS + 1):
            message = self._llm.chat(messages, tools=TOOL_SCHEMAS)
            messages.append(_assistant_message_to_dict(message))

            tool_calls = message.tool_calls or []
            if not tool_calls:
                return message.content or ""

            for tool_call in tool_calls:
                name = tool_call.function.name
                arguments = tool_call.function.arguments or "{}"
                logger.info("第%d轮: 调用工具 %s(%s)", iteration, name, arguments[:100])
                handler = TOOL_REGISTRY.get(name)
                if handler is not None:
                    result = await handler(arguments)
                else:
                    result = json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
                logger.info("工具 %s 返回: %s", name, result[:200])
                messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": result}
                )
        return None

    async def _parse_and_validate(
        self, messages: list[dict[str, Any]], final_content: str
    ) -> TripPlan | None:
        """提取 JSON + pydantic 校验；失败则把错误回给 LLM 修正，最多重试 JSON_RETRY_LIMIT 次。"""
        content = final_content
        for attempt in range(JSON_RETRY_LIMIT + 1):
            try:
                return TripPlan.model_validate(extract_json(content))
            except (JsonExtractionError, ValidationError) as exc:
                if attempt >= JSON_RETRY_LIMIT:
                    logger.error("行程 JSON 校验最终失败: %s", _format_validation_error(exc))
                    return None
                logger.warning("行程 JSON 校验失败（第%d次），请求 LLM 修正", attempt + 1)
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "你刚才输出的 JSON 未通过校验，错误信息如下：\n"
                            f"{_format_validation_error(exc)}\n"
                            "请严格按照 system 提示词中的格式要求，输出修正后的完整 JSON。只输出 JSON。"
                        ),
                    }
                )
                message = self._llm.chat(messages, tools=TOOL_SCHEMAS)
                messages.append(_assistant_message_to_dict(message))
                content = message.content or ""
        return None


# ============ 全局单例 ============

_planner: TripPlannerAgent | None = None


def get_trip_planner_agent() -> TripPlannerAgent:
    """获取全局 Agent 单例（懒加载）。"""
    global _planner
    if _planner is None:
        _planner = SimpleTripPlannerAgent()
        logger.info("TripPlannerAgent 初始化完成")
    return _planner
