"""Step 6 验收：工具 handler 测试（stub 服务，不联网、不花 token）。

验证三条铁律：
1. handler 永不抛异常（非法 JSON / 缺参数 / 服务报错都返回 error JSON）
2. 参数防御
3. 结果裁剪（只回填 LLM 需要的字段）
"""

import json

import pytest

import app.agent.tools.amap_tools as amap_tools
from app.agent.tools.amap_tools import (
    TOOL_REGISTRY,
    TOOL_SCHEMAS,
    geocode_handler,
    get_tool_handler,
    get_weather_handler,
    plan_route_handler,
    search_poi_handler,
)
from app.schemas.common import Location
from app.schemas.map import GeocodeResult, POIInfo, RouteInfo, WeatherInfo
from app.services.amap_service import AmapError


class StubAmapService:
    """可控的服务桩：默认返回正常数据，可切换为抛错模式。"""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def search_poi(self, keywords: str, city: str, limit: int = 10) -> list[POIInfo]:
        if self.fail:
            raise AmapError("访问已超出配额", "10044")
        return [
            POIInfo(
                id="B000A7O1CU",
                name="故宫博物院",
                type="风景名胜;景点",
                address="景山前街4号",
                location=Location(longitude=116.397, latitude=39.916),
                tel="010-65132241",
            )
        ]

    async def get_weather(self, city: str) -> list[WeatherInfo]:
        if self.fail:
            raise AmapError("天气服务不可用")
        return [WeatherInfo(date="2026-09-01", day_weather="晴", day_temp=28, night_temp=18)]

    async def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        mode: str = "walking",
        origin_city: str | None = None,
        destination_city: str | None = None,
    ) -> RouteInfo:
        if mode not in ("walking", "driving", "transit"):
            raise AmapError(f"不支持的路线类型: {mode!r}")
        if self.fail:
            raise AmapError("路线规划失败")
        return RouteInfo(distance=1500.0, duration=1200, route_type=mode, description="步行约 1.5 公里")

    async def geocode(self, address: str, city: str | None = None) -> GeocodeResult:
        if self.fail:
            raise AmapError("地址未找到")
        return GeocodeResult(
            location=Location(longitude=116.407, latitude=39.904),
            adcode="110000",
            city="北京市",
            formatted_address="北京市",
        )


@pytest.fixture
def stub_service(monkeypatch: pytest.MonkeyPatch) -> StubAmapService:
    stub = StubAmapService()
    monkeypatch.setattr(amap_tools, "get_amap_service", lambda: stub)
    return stub


# ============ 正常路径 + 结果裁剪 ============


async def test_search_poi_handler_success_and_trimming(stub_service: StubAmapService) -> None:
    result = json.loads(await search_poi_handler('{"keywords": "故宫", "city": "北京"}'))
    assert result["pois"][0]["name"] == "故宫博物院"
    # 裁剪验证：不回传 id/tel，只保留 LLM 需要的字段
    assert set(result["pois"][0].keys()) == {"name", "type", "address", "location"}
    assert result["pois"][0]["location"] == {"longitude": 116.397, "latitude": 39.916}


async def test_get_weather_handler_success(stub_service: StubAmapService) -> None:
    result = json.loads(await get_weather_handler('{"city": "北京"}'))
    assert result["forecasts"][0]["day_weather"] == "晴"
    assert result["forecasts"][0]["day_temp"] == 28


async def test_plan_route_handler_success(stub_service: StubAmapService) -> None:
    raw = '{"origin": "故宫博物院", "destination": "景山公园", "mode": "walking"}'
    result = json.loads(await plan_route_handler(raw))
    assert result == {
        "distance_m": 1500.0,
        "duration_s": 1200,
        "mode": "walking",
        "description": "步行约 1.5 公里",
    }


async def test_geocode_handler_success(stub_service: StubAmapService) -> None:
    result = json.loads(await geocode_handler('{"address": "北京"}'))
    assert result["adcode"] == "110000"
    assert result["location"]["longitude"] == 116.407


# ============ 铁律 1：永不抛异常 ============


async def test_invalid_json_arguments(stub_service: StubAmapService) -> None:
    result = json.loads(await search_poi_handler("{not valid json"))
    assert "error" in result


async def test_missing_required_arguments(stub_service: StubAmapService) -> None:
    result = json.loads(await search_poi_handler('{"city": "北京"}'))
    assert "keywords" in result["error"]


async def test_service_error_returns_error_json(stub_service: StubAmapService) -> None:
    stub_service.fail = True
    result = json.loads(await search_poi_handler('{"keywords": "故宫", "city": "北京"}'))
    assert "配额" in result["error"]


async def test_unknown_route_mode_returns_error_json(stub_service: StubAmapService) -> None:
    raw = '{"origin": "故宫", "destination": "颐和园", "mode": "flying"}'
    result = json.loads(await plan_route_handler(raw))
    assert "error" in result


# ============ 注册表一致性 ============


def test_registry_matches_schemas() -> None:
    """每个 schema 定义的工具都必须有 handler，反之亦然。"""
    schema_names = {schema["function"]["name"] for schema in TOOL_SCHEMAS}
    assert schema_names == set(TOOL_REGISTRY.keys())


def test_schemas_shape() -> None:
    """工具定义符合 OpenAI function calling 格式。"""
    for schema in TOOL_SCHEMAS:
        assert schema["type"] == "function"
        function = schema["function"]
        assert function["name"] and function["description"]
        assert function["parameters"]["type"] == "object"


def test_get_tool_handler() -> None:
    assert get_tool_handler("search_poi") is search_poi_handler
    assert get_tool_handler("not_exist") is None
