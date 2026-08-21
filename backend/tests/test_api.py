"""Step 9 验收：API 路由层测试（TestClient + stub，零 token 消耗）。

覆盖：
- /health 存活探针
- /api/map/* 三个接口的信封格式 + AmapError → 502
- /api/trip/plan 的信封格式、agent 违约兜底、请求校验 422
- 未知异常 → 500 信封（不泄漏堆栈）
"""

import pytest
from fastapi.testclient import TestClient

import app.api.routes.map as map_route
import app.api.routes.trip as trip_route
from app.main import app
from app.schemas.common import Location
from app.schemas.map import GeocodeResult, POIInfo, RouteInfo, WeatherInfo
from app.agent.trip_planner import _create_fallback_plan
from app.schemas.trip import TripPlan, TripRequest
from app.services.amap_service import AmapError

VALID_REQUEST_BODY = {
    "city": "北京",
    "start_date": "2026-09-01",
    "end_date": "2026-09-01",
    "transportation": "公共交通",
    "accommodation": "经济型酒店",
    "preferences": ["历史文化"],
    "free_text_input": "",
}


class StubAmapService:
    """可控服务桩：fail=True 时全部方法抛 AmapError。"""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def _check(self) -> None:
        if self.fail:
            raise AmapError("访问已超出配额", "10044")

    async def search_poi(self, keywords: str, city: str, limit: int = 10) -> list[POIInfo]:
        self._check()
        return [
            POIInfo(
                id="B000A7O1CU",
                name="故宫博物院",
                type="风景名胜;景点",
                address="景山前街4号",
                location=Location(longitude=116.397, latitude=39.916),
            )
        ]

    async def get_weather(self, city: str) -> list[WeatherInfo]:
        self._check()
        return [WeatherInfo(date="2026-09-01", day_weather="晴", day_temp=28, night_temp=18)]

    async def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        mode: str = "walking",
        origin_city: str | None = None,
        destination_city: str | None = None,
    ) -> RouteInfo:
        self._check()
        return RouteInfo(distance=1500.0, duration=1200, route_type=mode, description="步行约 1.5 公里")

    async def geocode(self, address: str, city: str | None = None) -> GeocodeResult:
        self._check()
        return GeocodeResult(
            location=Location(longitude=116.407, latitude=39.904),
            adcode="110000",
            city="北京市",
            formatted_address="北京市",
        )


class StubAgent:
    """可控 agent 桩：可返回指定计划，或模拟违约抛异常。"""

    def __init__(self, plan: TripPlan | None = None, error: Exception | None = None) -> None:
        self._plan = plan
        self._error = error
        self.received: list[TripRequest] = []

    async def plan(self, request: TripRequest) -> TripPlan:
        self.received.append(request)
        if self._error is not None:
            raise self._error
        assert self._plan is not None
        return self._plan


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def stub_amap(monkeypatch: pytest.MonkeyPatch) -> StubAmapService:
    stub = StubAmapService()
    monkeypatch.setattr(map_route, "get_amap_service", lambda: stub)
    return stub


# ============ health ============


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


# ============ map 接口 ============


def test_map_poi_envelope(client: TestClient, stub_amap: StubAmapService) -> None:
    response = client.get("/api/map/poi", params={"keywords": "故宫", "city": "北京"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"][0]["name"] == "故宫博物院"
    assert body["data"][0]["location"]["longitude"] == 116.397


def test_map_poi_requires_params(client: TestClient, stub_amap: StubAmapService) -> None:
    assert client.get("/api/map/poi").status_code == 422
    assert client.get("/api/map/poi", params={"keywords": "故宫"}).status_code == 422


def test_map_weather_envelope(client: TestClient, stub_amap: StubAmapService) -> None:
    response = client.get("/api/map/weather", params={"city": "北京"})
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["data"][0]["day_weather"] == "晴"


def test_map_route_envelope(client: TestClient, stub_amap: StubAmapService) -> None:
    response = client.post(
        "/api/map/route",
        json={"origin": "故宫", "destination": "景山公园", "mode": "walking"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["data"]["distance"] == 1500.0
    assert body["data"]["route_type"] == "walking"


def test_map_route_rejects_empty_origin(client: TestClient, stub_amap: StubAmapService) -> None:
    response = client.post("/api/map/route", json={"origin": "", "destination": "景山公园"})
    assert response.status_code == 422


def test_map_amap_error_returns_502_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing = StubAmapService(fail=True)
    monkeypatch.setattr(map_route, "get_amap_service", lambda: failing)
    response = client.get("/api/map/poi", params={"keywords": "故宫", "city": "北京"})
    assert response.status_code == 502
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert "配额" in body["message"]


def test_map_unexpected_error_returns_500_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ExplodingService(StubAmapService):
        async def search_poi(self, keywords: str, city: str, limit: int = 10):
            raise RuntimeError("boom")

    monkeypatch.setattr(map_route, "get_amap_service", lambda: ExplodingService())
    # raise_server_exceptions=False 才能观察到 500 处理器生成的信封
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/map/poi", params={"keywords": "故宫", "city": "北京"})
    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert "boom" not in body["message"]  # 堆栈细节不泄漏给前端


# ============ trip 接口 ============


def test_trip_plan_success_envelope(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    request = TripRequest(**VALID_REQUEST_BODY)
    stub = StubAgent(plan=_create_fallback_plan(request))
    monkeypatch.setattr(trip_route, "get_trip_planner_agent", lambda: stub)

    response = client.post("/api/trip/plan", json=VALID_REQUEST_BODY)
    assert response.status_code == 200  # 成功失败都 200，看信封
    body = response.json()
    assert body["success"] is True
    assert body["data"]["city"] == "北京"
    assert len(body["data"]["days"]) == 1
    assert len(stub.received) == 1  # 请求对象正确传入 agent
    assert stub.received[0].city == "北京"


def test_trip_plan_agent_violates_contract(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """agent 契约是不抛异常，但路由层仍要有最后防线。"""
    stub = StubAgent(error=RuntimeError("agent 内部炸了"))
    monkeypatch.setattr(trip_route, "get_trip_planner_agent", lambda: stub)

    response = client.post("/api/trip/plan", json=VALID_REQUEST_BODY)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert "失败" in body["message"]


def test_trip_plan_invalid_request_returns_422(client: TestClient) -> None:
    bad_body = {**VALID_REQUEST_BODY, "start_date": "2026/09/01"}  # 日期格式非法
    response = client.post("/api/trip/plan", json=bad_body)
    assert response.status_code == 422


def test_trip_plan_date_order_returns_422(client: TestClient) -> None:
    bad_body = {**VALID_REQUEST_BODY, "start_date": "2026-09-03", "end_date": "2026-09-01"}
    response = client.post("/api/trip/plan", json=bad_body)
    assert response.status_code == 422
