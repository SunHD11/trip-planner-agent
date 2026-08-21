"""高德地图 Web 服务 REST 客户端。

替换原 hello-agents 仓库基于 MCPTool(uvx amap-mcp-server) 的封装：
直接用 httpx 调高德 REST API，返回已解析、已校验的 Pydantic 模型
（原仓库此层全是 TODO 空实现，这里是真正实现）。

三个关键坑（详见 docs/IMPLEMENTATION_GUIDE.md Step 3）：
- 天气 API 只认 adcode、不认城市名 → get_weather 内部先 geocode 转换并缓存
- 路线 API 只认 "lng,lat" 坐标、不认地址 → plan_route 内部先 geocode 两端
- 高德字段缺失时返回 [] 而非字符串 → _as_str 统一防御
"""

import logging
from typing import Any

import httpx

from app.schemas.common import Location
from app.schemas.map import GeocodeResult, POIInfo, RouteInfo, WeatherInfo

logger = logging.getLogger(__name__)

AMAP_BASE_URL = "https://restapi.amap.com"
AMAP_TIMEOUT_SECONDS = 15.0

_ROUTE_ENDPOINTS: dict[str, str] = {
    "walking": "/v3/direction/walking",
    "driving": "/v3/direction/driving",
    "transit": "/v3/direction/transit/integrated",
}
_MODE_LABELS: dict[str, str] = {
    "walking": "步行",
    "driving": "驾车",
    "transit": "公共交通",
}


class AmapError(Exception):
    """高德 API 业务错误（status != "1"、地址无结果、解析失败等）。"""

    def __init__(self, message: str, info_code: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.info_code = info_code


# ============ 解析工具 ============


def _as_str(value: Any) -> str:
    """高德字段缺失时常返回 [] 而非字符串，统一转成字符串。"""
    return value if isinstance(value, str) else ""


def _parse_location(raw: Any) -> Location | None:
    """把高德 "lng,lat" 字符串解析为 Location；非法返回 None。"""
    parts = _as_str(raw).split(",")
    if len(parts) != 2:
        return None
    try:
        return Location(longitude=float(parts[0]), latitude=float(parts[1]))
    except ValueError:
        return None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _format_distance(meters: float) -> str:
    if meters >= 1000:
        return f"{meters / 1000:.1f} 公里"
    return f"{int(meters)} 米"


def _format_duration(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600} 小时 {(seconds % 3600) // 60} 分钟"
    if seconds >= 60:
        return f"{seconds // 60} 分钟"
    return f"{seconds} 秒"


# ============ 服务本体 ============


class AmapService:
    """高德地图 REST 客户端。

    httpx.AsyncClient 由外部注入：
    - 生产环境由 get_amap_service() 创建、FastAPI lifespan 负责关闭
    - 测试中注入 MockTransport 的 client，无需联网
    """

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client
        self._adcode_cache: dict[str, str] = {}

    async def aclose(self) -> None:
        """关闭底层 HTTP 客户端。"""
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, str | int]) -> dict[str, Any]:
        """统一请求：附加 key、检查 HTTP/业务状态、返回 JSON。"""
        merged: dict[str, str | int] = {**params, "key": self._api_key, "output": "JSON"}
        try:
            response = await self._client.get(f"{AMAP_BASE_URL}{path}", params=merged)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AmapError(f"请求高德 API 失败({path}): {exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise AmapError(f"高德 API 返回非 JSON({path})") from exc
        if data.get("status") != "1":
            info = _as_str(data.get("info")) or "高德返回未知错误"
            raise AmapError(info, _as_str(data.get("infocode")))
        return data

    # ---- 地理编码（其他方法的内部依赖，也可独立调用） ----

    async def geocode(self, address: str, city: str | None = None) -> GeocodeResult:
        """地址 → 坐标 + adcode。城市名也可当 address 传入。"""
        params: dict[str, str | int] = {"address": address}
        if city:
            params["city"] = city
        data = await self._get("/v3/geocode/geo", params)
        geocodes = data.get("geocodes") or []
        if not geocodes:
            raise AmapError(f"地址未找到: {address!r}")
        first = geocodes[0]
        location = _parse_location(first.get("location"))
        if location is None:
            raise AmapError(f"地址坐标解析失败: {address!r}")
        return GeocodeResult(
            location=location,
            adcode=_as_str(first.get("adcode")),
            citycode=_as_str(first.get("citycode")),
            city=_as_str(first.get("city")),
            formatted_address=_as_str(first.get("formatted_address")),
        )

    # ---- POI 搜索 ----

    async def search_poi(self, keywords: str, city: str, limit: int = 10) -> list[POIInfo]:
        """关键词搜索 POI，只保留带坐标的结果。"""
        data = await self._get(
            "/v3/place/text",
            {"keywords": keywords, "city": city, "citylimit": "true", "offset": limit, "page": 1},
        )
        pois: list[POIInfo] = []
        for raw in data.get("pois") or []:
            location = _parse_location(raw.get("location"))
            if location is None:
                continue
            pois.append(
                POIInfo(
                    id=_as_str(raw.get("id")),
                    name=_as_str(raw.get("name")),
                    type=_as_str(raw.get("type")),
                    address=_as_str(raw.get("address")),
                    location=location,
                    tel=_as_str(raw.get("tel")) or None,
                )
            )
        return pois

    # ---- 天气（内部自动 城市名 → adcode） ----

    async def get_weather(self, city: str) -> list[WeatherInfo]:
        """查询未来几天天气预报。city 传城市名即可，内部自动转 adcode。"""
        adcode = self._adcode_cache.get(city)
        if adcode is None:
            geocoded = await self.geocode(city)
            if not geocoded.adcode:
                raise AmapError(f"无法获取城市 adcode: {city!r}")
            adcode = geocoded.adcode
            self._adcode_cache[city] = adcode
        data = await self._get(
            "/v3/weather/weatherInfo", {"city": adcode, "extensions": "all"}
        )
        forecasts = data.get("forecasts") or []
        if not forecasts:
            raise AmapError(f"未查到天气: {city!r}")
        return [
            WeatherInfo(
                date=_as_str(cast.get("date")),
                day_weather=_as_str(cast.get("dayweather")),
                night_weather=_as_str(cast.get("nightweather")),
                day_temp=_as_str(cast.get("daytemp")),
                night_temp=_as_str(cast.get("nighttemp")),
                wind_direction=_as_str(cast.get("daywind")),
                wind_power=_as_str(cast.get("daypower")),
            )
            for cast in forecasts[0].get("casts") or []
        ]

    # ---- 路线规划（内部自动 地址 → 坐标） ----

    async def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        mode: str = "walking",
        origin_city: str | None = None,
        destination_city: str | None = None,
    ) -> RouteInfo:
        """规划两点间路线。起终点传地址即可，内部自动地理编码。"""
        endpoint = _ROUTE_ENDPOINTS.get(mode)
        if endpoint is None:
            raise AmapError(f"不支持的路线类型: {mode!r}（可选 walking/driving/transit）")

        origin = await self.geocode(origin_address, origin_city)
        destination = await self.geocode(destination_address, destination_city)
        params: dict[str, str | int] = {
            "origin": f"{origin.location.longitude},{origin.location.latitude}",
            "destination": f"{destination.location.longitude},{destination.location.latitude}",
        }
        if mode == "transit":
            city = origin_city or origin.city
            if not city:
                raise AmapError("公交路线规划需要起点城市（origin_city）")
            params["city"] = city
            params["cityd"] = destination_city or destination.city or city

        data = await self._get(endpoint, params)
        route = data.get("route") or {}
        if mode == "transit":
            distance = _to_float(route.get("distance"))
            transits = route.get("transits") or []
            duration = _to_int(transits[0].get("duration")) if transits else 0
        else:
            paths = route.get("paths") or []
            if not paths:
                raise AmapError(f"高德未返回路线: {origin_address} → {destination_address}")
            distance = _to_float(paths[0].get("distance"))
            duration = _to_int(paths[0].get("duration"))

        label = _MODE_LABELS[mode]
        description = f"{label}约 {_format_distance(distance)}，耗时约 {_format_duration(duration)}"
        logger.info("路线规划完成: %s → %s (%s) %s", origin_address, destination_address, mode, description)
        return RouteInfo(distance=distance, duration=duration, route_type=mode, description=description)


# ============ 全局单例 ============

_amap_service: AmapService | None = None


def get_amap_service() -> AmapService:
    """获取全局单例（懒加载：首次调用时才读 settings 创建）。"""
    global _amap_service
    if _amap_service is None:
        from app.config import settings  # 延迟导入，避免模块级耦合 .env 校验

        client = httpx.AsyncClient(timeout=AMAP_TIMEOUT_SECONDS)
        _amap_service = AmapService(api_key=settings.amap_api_key, client=client)
        logger.info("AmapService 初始化完成")
    return _amap_service


async def close_amap_service() -> None:
    """关闭全局 HTTP 客户端（由 FastAPI lifespan 在应用关闭时调用）。"""
    global _amap_service
    if _amap_service is not None:
        await _amap_service.aclose()
        _amap_service = None
