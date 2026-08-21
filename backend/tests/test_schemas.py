"""Step 1 验收：数据契约测试。

覆盖目标：
1. 与前端 types/trip.ts 形状一致的样例 JSON 能成功反序列化
2. 非法日期 / 日期倒序被拒绝
3. calc_travel_days 天数推算正确
4. WeatherInfo 温度清洗（"25°C" → 25）
5. ApiResponse 信封序列化形状正确
"""

import pytest
from pydantic import ValidationError

from app.schemas.common import ApiResponse, Location
from app.schemas.map import POIInfo, RouteInfo, WeatherInfo
from app.schemas.trip import (
    Attraction,
    DayPlan,
    Meal,
    TripPlan,
    TripPlanResponse,
    TripRequest,
    calc_travel_days,
)

# ============ 样例数据（模拟前端 / LLM 产出的 JSON） ============

VALID_REQUEST = {
    "city": "北京",
    "start_date": "2026-09-01",
    "end_date": "2026-09-03",
    "transportation": "公共交通",
    "accommodation": "经济型酒店",
    "preferences": ["历史文化", "美食"],
    "free_text_input": "希望多安排一些博物馆",
}

VALID_PLAN = {
    "city": "北京",
    "start_date": "2026-09-01",
    "end_date": "2026-09-03",
    "days": [
        {
            "date": "2026-09-01",
            "day_index": 0,
            "description": "故宫-景山-南锣鼓巷",
            "transportation": "地铁+步行",
            "accommodation": "经济型酒店",
            "attractions": [
                {
                    "name": "故宫博物院",
                    "address": "北京市东城区景山前街4号",
                    "location": {"longitude": 116.397, "latitude": 39.916},
                    "visit_duration": 180,
                    "description": "明清两代皇家宫殿",
                    "ticket_price": 60,
                },
                {"name": "景山公园"},  # 仅必填字段，验证可选项缺省
            ],
            "meals": [
                {"type": "breakfast", "name": "庆丰包子铺", "estimated_cost": 20},
                {"type": "lunch", "name": "四季民福烤鸭"},
                {"type": "dinner", "name": "东来顺", "estimated_cost": 120},
            ],
        }
    ],
    "overall_suggestions": "9月初北京天气宜人，建议错峰游览故宫。",
    "budget": {
        "total": 1500,
        "total_attractions": 60,
        "total_hotels": 800,
        "total_meals": 400,
        "total_transportation": 240,
    },
}


# ============ TripRequest ============


def test_trip_request_valid() -> None:
    req = TripRequest.model_validate(VALID_REQUEST)
    assert req.city == "北京"
    assert req.preferences == ["历史文化", "美食"]


def test_trip_request_optional_defaults() -> None:
    minimal = {k: VALID_REQUEST[k] for k in ("city", "start_date", "end_date", "transportation", "accommodation")}
    req = TripRequest.model_validate(minimal)
    assert req.preferences == []
    assert req.free_text_input == ""


def test_trip_request_bad_date_format_rejected() -> None:
    with pytest.raises(ValidationError):
        TripRequest.model_validate({**VALID_REQUEST, "start_date": "2026/09/01"})


def test_trip_request_end_before_start_rejected() -> None:
    with pytest.raises(ValidationError):
        TripRequest.model_validate(
            {**VALID_REQUEST, "start_date": "2026-09-05", "end_date": "2026-09-01"}
        )


# ============ calc_travel_days ============


def test_calc_travel_days() -> None:
    assert calc_travel_days("2026-09-01", "2026-09-01") == 1
    assert calc_travel_days("2026-09-01", "2026-09-03") == 3
    assert calc_travel_days("2026-12-30", "2027-01-02") == 4  # 跨年


# ============ TripPlan（前端契约形状） ============


def test_trip_plan_from_frontend_shape() -> None:
    plan = TripPlan.model_validate(VALID_PLAN)
    assert plan.city == "北京"
    day = plan.days[0]
    assert day.day_index == 0
    assert day.attractions[0].location == Location(longitude=116.397, latitude=39.916)
    assert day.attractions[1].address is None  # 可选字段缺省
    assert day.meals[1].estimated_cost is None
    assert plan.budget is not None and plan.budget.total == 1500


def test_trip_plan_minimal() -> None:
    minimal = {
        "city": "上海",
        "start_date": "2026-10-01",
        "end_date": "2026-10-02",
        "days": [],
    }
    plan = TripPlan.model_validate(minimal)
    assert plan.overall_suggestions is None
    assert plan.budget is None


def test_trip_plan_response_envelope() -> None:
    ok = TripPlanResponse(success=True, message="生成成功", data=TripPlan.model_validate(VALID_PLAN))
    fail = TripPlanResponse(success=False, message="服务繁忙", data=None)
    assert ok.data is not None
    assert fail.data is None


def test_schema_immutability() -> None:
    """frozen 模型禁止原地修改（项目的不可变约定）。"""
    attraction = Attraction(name="故宫博物院")
    with pytest.raises(ValidationError):
        attraction.name = "篡改"  # type: ignore[misc]


# ============ WeatherInfo 温度清洗 ============


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("25", 25), ("25°C", 25), ("25℃", 25), (" 18° ", 18), (-3, -3), ("abc", 0)],
)
def test_weather_temperature_cleaning(raw: object, expected: int) -> None:
    info = WeatherInfo.model_validate({"date": "2026-09-01", "day_temp": raw, "night_temp": raw})
    assert info.day_temp == expected
    assert info.night_temp == expected


# ============ 地图模型与信封 ============


def test_poi_info_and_envelope_shape() -> None:
    poi = POIInfo(
        id="B000A7O1CU",
        name="故宫博物院",
        type="风景名胜;景点",
        address="景山前街4号",
        location=Location(longitude=116.397, latitude=39.916),
    )
    envelope = ApiResponse[list[POIInfo]](success=True, message="POI搜索成功", data=[poi])
    dumped = envelope.model_dump()
    # 信封必须恰好是前端约定的三个键
    assert set(dumped.keys()) == {"success", "message", "data"}
    assert dumped["data"][0]["location"]["longitude"] == 116.397


def test_route_info() -> None:
    route = RouteInfo(distance=12500.0, duration=2700, route_type="transit", description="地铁1号线转5号线")
    assert route.distance == 12500.0
    with pytest.raises(ValidationError):
        RouteInfo(distance=-1, duration=0, route_type="walking")
