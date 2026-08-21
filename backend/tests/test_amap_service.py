"""Step 3 验收：amap_service 单元测试（MockTransport，不联网）。"""

import httpx
import pytest

from app.services.amap_service import AmapError, AmapService


def _service(handler) -> AmapService:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return AmapService(api_key="test-key", client=client)


# ============ search_poi ============


async def test_search_poi_parses_and_skips_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v3/place/text"
        assert request.url.params["key"] == "test-key"
        assert request.url.params["citylimit"] == "true"
        return httpx.Response(
            200,
            json={
                "status": "1",
                "pois": [
                    {
                        "id": "B1",
                        "name": "故宫博物院",
                        "type": "风景名胜;景点",
                        "address": "景山前街4号",
                        "location": "116.397,39.916",
                        "tel": "010-65132241",
                    },
                    # 无坐标的 POI 应被跳过
                    {"id": "B2", "name": "无坐标点", "address": [], "location": []},
                    # address/tel 为 [] 的防御
                    {"id": "B3", "name": "景山公园", "type": "", "address": [], "location": "116.396,39.923", "tel": []},
                ],
            },
        )

    service = _service(handler)
    pois = await service.search_poi("故宫", "北京")
    assert [p.name for p in pois] == ["故宫博物院", "景山公园"]
    assert pois[0].location.longitude == 116.397
    assert pois[0].tel == "010-65132241"
    assert pois[1].address == ""  # [] → ""
    assert pois[1].tel is None  # [] → None


async def test_search_poi_empty_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "1", "pois": []})

    assert await _service(handler).search_poi("不存在的地方", "北京") == []


# ============ 错误处理 ============


async def test_status_zero_raises_amap_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"}
        )

    with pytest.raises(AmapError) as exc_info:
        await _service(handler).search_poi("故宫", "北京")
    assert exc_info.value.info_code == "10001"
    assert "INVALID_USER_KEY" in exc_info.value.message


async def test_network_error_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(AmapError, match="请求高德 API 失败"):
        await _service(handler).search_poi("故宫", "北京")


# ============ geocode ============


async def test_geocode_parses_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "1",
                "geocodes": [
                    {
                        "location": "116.407,39.904",
                        "adcode": "110000",
                        "citycode": "010",
                        "city": "北京市",
                        "formatted_address": "北京市",
                    }
                ],
            },
        )

    result = await _service(handler).geocode("北京")
    assert result.adcode == "110000"
    assert result.location.latitude == 39.904


async def test_geocode_empty_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "1", "geocodes": []})

    with pytest.raises(AmapError, match="地址未找到"):
        await _service(handler).geocode("火星基地一号")


# ============ get_weather（adcode 转换 + 缓存） ============


async def test_get_weather_converts_city_to_adcode_and_caches() -> None:
    calls = {"geocode": 0, "weather": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/geocode/geo":
            calls["geocode"] += 1
            return httpx.Response(
                200,
                json={"status": "1", "geocodes": [{"location": "116.407,39.904", "adcode": "110000", "city": "北京市"}]},
            )
        assert request.url.path == "/v3/weather/weatherInfo"
        assert request.url.params["city"] == "110000"  # 必须是 adcode 而非城市名
        assert request.url.params["extensions"] == "all"
        calls["weather"] += 1
        return httpx.Response(
            200,
            json={
                "status": "1",
                "forecasts": [
                    {
                        "casts": [
                            {
                                "date": "2026-09-01",
                                "dayweather": "晴",
                                "nightweather": "多云",
                                "daytemp": "28",
                                "nighttemp": "18",
                                "daywind": "南",
                                "daypower": "≤3",
                            }
                        ]
                    }
                ],
            },
        )

    service = _service(handler)
    first = await service.get_weather("北京")
    second = await service.get_weather("北京")  # 第二次走缓存
    assert calls == {"geocode": 1, "weather": 2}
    assert first == second
    assert first[0].day_temp == 28  # "28" → 28
    assert first[0].day_weather == "晴"


# ============ plan_route（地址 → 坐标） ============


def _route_geocode_handler(request: httpx.Request) -> tuple[str, httpx.Response] | None:
    """共用的地理编码分支：故宫 → 固定坐标 A，颐和园 → 固定坐标 B。"""
    if request.url.path != "/v3/geocode/geo":
        return None
    address = request.url.params["address"]
    location = "116.397,39.916" if "故宫" in address else "116.275,40.000"
    response = httpx.Response(
        200,
        json={"status": "1", "geocodes": [{"location": location, "adcode": "110000", "city": "北京市"}]},
    )
    return address, response


async def test_plan_route_walking_geocodes_both_endpoints() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        geocode = _route_geocode_handler(request)
        if geocode is not None:
            return geocode[1]
        assert request.url.path == "/v3/direction/walking"
        # 坐标必须是地理编码的结果（地址已被转换）
        assert request.url.params["origin"] == "116.397,39.916"
        assert request.url.params["destination"] == "116.275,40.0"
        return httpx.Response(
            200, json={"status": "1", "route": {"paths": [{"distance": "15000", "duration": "5400"}]}}
        )

    route = await _service(handler).plan_route("故宫博物院", "颐和园", mode="walking")
    assert route.distance == 15000.0
    assert route.duration == 5400
    assert route.route_type == "walking"
    assert "步行" in route.description


async def test_plan_route_transit_passes_cities() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        geocode = _route_geocode_handler(request)
        if geocode is not None:
            return geocode[1]
        assert request.url.path == "/v3/direction/transit/integrated"
        assert request.url.params["city"] == "北京"
        assert request.url.params["cityd"] == "北京"
        return httpx.Response(
            200, json={"status": "1", "route": {"distance": "22000", "transits": [{"duration": "3600"}]}}
        )

    route = await _service(handler).plan_route(
        "故宫博物院", "颐和园", mode="transit", origin_city="北京", destination_city="北京"
    )
    assert route.distance == 22000.0
    assert route.duration == 3600
    assert "公共交通" in route.description


async def test_plan_route_unknown_mode_raises() -> None:
    service = _service(lambda r: httpx.Response(200, json={}))
    with pytest.raises(AmapError, match="不支持的路线类型"):
        await service.plan_route("故宫博物院", "颐和园", mode="flying")
