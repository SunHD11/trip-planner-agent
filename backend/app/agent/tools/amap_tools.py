"""Agent 工具注册表：把 amap_service 封装成 LLM 可调用的工具。

三条铁律（所有 handler 必须遵守）：
1. handler 永远返回 JSON 字符串，永不抛异常——错误也包装成 {"error": ...}
   回填给 LLM，让它换个姿势重试，而不是崩掉整个循环
2. 参数解析要防御：arguments 是 JSON 字符串，可能非法、可能缺字段
3. 结果要裁剪：只保留 LLM 需要的字段，控制 token 消耗

对外导出两样东西（Step 8 主循环只需要这两个）：
- TOOL_SCHEMAS: OpenAI function calling 格式的工具定义列表
- TOOL_REGISTRY: {工具名: handler} 映射
"""

import json
import logging
from typing import Any, Awaitable, Callable

from app.services.amap_service import AmapError, get_amap_service

logger = logging.getLogger(__name__)

# handler 统一签名：接收 LLM 给的 arguments JSON 字符串，返回结果 JSON 字符串
ToolHandler = Callable[[str], Awaitable[str]]


# ============ 内部工具函数 ============


def _error_payload(message: str) -> str:
    """把错误包装成回填给 LLM 的 JSON 字符串。"""
    return json.dumps({"error": message}, ensure_ascii=False)


def _parse_arguments(raw: str) -> dict[str, Any] | None:
    """防御性解析 LLM 给的 arguments JSON 字符串；非法返回 None。"""
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


# ============ 四个工具 handler ============


async def search_poi_handler(arguments_json: str) -> str:
    """搜索景点/餐厅/酒店等 POI。"""
    arguments = _parse_arguments(arguments_json)
    if arguments is None:
        return _error_payload("工具参数不是合法 JSON")
    keywords = str(arguments.get("keywords") or "").strip()
    city = str(arguments.get("city") or "").strip()
    if not keywords or not city:
        return _error_payload("缺少必填参数：keywords（搜索关键词）、city（城市）")
    try:
        pois = await get_amap_service().search_poi(keywords, city)
    except AmapError as exc:
        return _error_payload(f"POI 搜索失败: {exc.message}")
    except Exception as exc:
        logger.exception("search_poi 工具执行异常")
        return _error_payload(f"POI 搜索异常: {exc}")
    payload = {
        "pois": [
            {
                "name": poi.name,
                "type": poi.type,
                "address": poi.address,
                "location": {
                    "longitude": poi.location.longitude,
                    "latitude": poi.location.latitude,
                },
            }
            for poi in pois
        ]
    }
    return json.dumps(payload, ensure_ascii=False)


async def get_weather_handler(arguments_json: str) -> str:
    """查询城市未来几天天气预报。"""
    arguments = _parse_arguments(arguments_json)
    if arguments is None:
        return _error_payload("工具参数不是合法 JSON")
    city = str(arguments.get("city") or "").strip()
    if not city:
        return _error_payload("缺少必填参数：city（城市）")
    try:
        forecasts = await get_amap_service().get_weather(city)
    except AmapError as exc:
        return _error_payload(f"天气查询失败: {exc.message}")
    except Exception as exc:
        logger.exception("get_weather 工具执行异常")
        return _error_payload(f"天气查询异常: {exc}")
    payload = {"forecasts": [info.model_dump() for info in forecasts]}
    return json.dumps(payload, ensure_ascii=False)


async def plan_route_handler(arguments_json: str) -> str:
    """规划两点间路线（地址会自动转坐标）。"""
    arguments = _parse_arguments(arguments_json)
    if arguments is None:
        return _error_payload("工具参数不是合法 JSON")
    origin = str(arguments.get("origin") or "").strip()
    destination = str(arguments.get("destination") or "").strip()
    mode = str(arguments.get("mode") or "walking").strip()
    city = str(arguments.get("city") or "").strip() or None
    if not origin or not destination:
        return _error_payload("缺少必填参数：origin（起点地址）、destination（终点地址）")
    try:
        route = await get_amap_service().plan_route(
            origin_address=origin,
            destination_address=destination,
            mode=mode,
            origin_city=city,
            destination_city=city,
        )
    except AmapError as exc:
        return _error_payload(f"路线规划失败: {exc.message}")
    except Exception as exc:
        logger.exception("plan_route 工具执行异常")
        return _error_payload(f"路线规划异常: {exc}")
    payload = {
        "distance_m": route.distance,
        "duration_s": route.duration,
        "mode": route.route_type,
        "description": route.description,
    }
    return json.dumps(payload, ensure_ascii=False)


async def geocode_handler(arguments_json: str) -> str:
    """把地址或地名转换为坐标和 adcode。"""
    arguments = _parse_arguments(arguments_json)
    if arguments is None:
        return _error_payload("工具参数不是合法 JSON")
    address = str(arguments.get("address") or "").strip()
    city = str(arguments.get("city") or "").strip() or None
    if not address:
        return _error_payload("缺少必填参数：address（地址或地名）")
    try:
        result = await get_amap_service().geocode(address, city)
    except AmapError as exc:
        return _error_payload(f"地理编码失败: {exc.message}")
    except Exception as exc:
        logger.exception("geocode 工具执行异常")
        return _error_payload(f"地理编码异常: {exc}")
    payload = {
        "formatted_address": result.formatted_address,
        "city": result.city,
        "adcode": result.adcode,
        "location": {
            "longitude": result.location.longitude,
            "latitude": result.location.latitude,
        },
    }
    return json.dumps(payload, ensure_ascii=False)


# ============ 工具定义（OpenAI function calling 格式） ============

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_poi",
            "description": (
                "在城市中搜索景点、餐厅、酒店等兴趣点（POI），返回名称、地址和真实坐标。"
                "查找景点（用用户偏好作为关键词，每个偏好搜索一次）、餐厅、酒店时必须使用本工具获取真实数据，"
                "禁止凭空编造任何地点信息。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {"type": "string", "description": "搜索关键词，如「博物馆」「火锅」「经济型酒店」"},
                    "city": {"type": "string", "description": "城市名称，如「北京」"},
                },
                "required": ["keywords", "city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "查询城市未来几天的天气预报（白天/夜间天气、温度、风力）。"
                "规划行程时必须调用一次，并在总体建议中体现天气对行程的影响。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，如「北京」"},
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_route",
            "description": (
                "规划两点之间的路线，返回距离和预计耗时。起终点传地址或地点名称即可。"
                "可用于验证景点之间的通行时间，帮助判断同一天景点安排是否顺路。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "起点地址或地点名称"},
                    "destination": {"type": "string", "description": "终点地址或地点名称"},
                    "mode": {
                        "type": "string",
                        "enum": ["walking", "driving", "transit"],
                        "description": "出行方式：walking 步行 / driving 驾车 / transit 公共交通，默认 walking",
                    },
                    "city": {"type": "string", "description": "所在城市（mode 为 transit 时需要）"},
                },
                "required": ["origin", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "geocode",
            "description": "把地址或地名转换为经纬度坐标和区域编码（adcode）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "address": {"type": "string", "description": "地址或地名"},
                    "city": {"type": "string", "description": "城市名称（可选，提高准确性）"},
                },
                "required": ["address"],
            },
        },
    },
]

TOOL_REGISTRY: dict[str, ToolHandler] = {
    "search_poi": search_poi_handler,
    "get_weather": get_weather_handler,
    "plan_route": plan_route_handler,
    "geocode": geocode_handler,
}


def get_tool_handler(name: str) -> ToolHandler | None:
    """按名称取 handler；未知工具返回 None（由调用方回填错误信息）。"""
    return TOOL_REGISTRY.get(name)
