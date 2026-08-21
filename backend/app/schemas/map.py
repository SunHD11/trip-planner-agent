"""地图服务数据模型：POI / 天气 / 路线。"""

from pydantic import Field, field_validator

from app.schemas.common import ApiResponse, BaseSchema, Location


class POIInfo(BaseSchema):
    """POI（兴趣点）信息，来自高德 place/text。"""

    id: str = Field(..., description="POI ID")
    name: str = Field(..., description="名称")
    type: str = Field(default="", description="类型，如「风景名胜;景点」")
    address: str = Field(default="", description="地址")
    location: Location = Field(..., description="经纬度坐标")
    tel: str | None = Field(default=None, description="电话")


class WeatherInfo(BaseSchema):
    """天气信息，来自高德 weather/weatherInfo 的 forecasts.casts。"""

    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_weather: str = Field(default="", description="白天天气")
    night_weather: str = Field(default="", description="夜间天气")
    day_temp: int = Field(default=0, description="白天温度（℃，纯数字）")
    night_temp: int = Field(default=0, description="夜间温度（℃，纯数字）")
    wind_direction: str = Field(default="", description="风向")
    wind_power: str = Field(default="", description="风力")

    @field_validator("day_temp", "night_temp", mode="before")
    @classmethod
    def _parse_temperature(cls, value: object) -> int:
        """清洗温度值：兼容 int 和 "25°C" / "25℃" 这类带单位字符串。"""
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            cleaned = (
                value.replace("°C", "").replace("℃", "").replace("°", "").strip()
            )
            try:
                return int(cleaned)
            except ValueError:
                return 0
        return 0


class GeocodeResult(BaseSchema):
    """地理编码结果（地址 → 坐标 + adcode）。

    高德「天气」只认 adcode、「路线」只认坐标，
    本模型是 amap_service 内部做这两个转换的中转载体。
    """

    location: Location = Field(..., description="经纬度坐标")
    adcode: str = Field(default="", description="区域编码（天气 API 需要）")
    citycode: str = Field(default="", description="城市编码")
    city: str = Field(default="", description="城市名")
    formatted_address: str = Field(default="", description="规范化地址")


class RouteInfo(BaseSchema):
    """路线信息，来自高德 direction/* 接口。"""

    distance: float = Field(..., ge=0, description="距离（米）")
    duration: int = Field(..., ge=0, description="耗时（秒）")
    route_type: str = Field(..., description="路线类型：walking/driving/transit")
    description: str = Field(default="", description="路线描述")


class RouteRequest(BaseSchema):
    """路线规划请求（POST /api/map/route 的 body）。"""

    origin: str = Field(..., min_length=1, description="起点地址或名称")
    destination: str = Field(..., min_length=1, description="终点地址或名称")
    mode: str = Field(default="walking", description="出行方式：walking/driving/transit")
    origin_city: str | None = Field(default=None, description="起点城市（公交规划必填）")
    destination_city: str | None = Field(default=None, description="终点城市")


# 套上统一信封的响应模型（泛型别名，可直接用于 FastAPI response_model）
POISearchResponse = ApiResponse[list[POIInfo]]
WeatherResponse = ApiResponse[list[WeatherInfo]]
RouteResponse = ApiResponse[RouteInfo]
