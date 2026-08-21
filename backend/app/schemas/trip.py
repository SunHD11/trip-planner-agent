"""旅行规划数据契约。

⚠️ 本模块严格镜像 frontend/src/types/trip.ts：
字段名、可选性必须与前端类型逐一对应，修改前请先对照前端。
"""

from datetime import date

from pydantic import Field, field_validator, model_validator

from app.schemas.common import BaseSchema, Location


def calc_travel_days(start_date: str, end_date: str) -> int:
    """由起止日期推算旅行天数（首尾都算，至少 1 天）。"""
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    return (end - start).days + 1


class TripRequest(BaseSchema):
    """旅行规划请求（对应前端 TripRequest）。"""

    city: str = Field(..., min_length=1, description="目的地城市")
    start_date: str = Field(..., description="开始日期 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期 YYYY-MM-DD")
    transportation: str = Field(..., description="交通方式，如「公共交通」")
    accommodation: str = Field(..., description="住宿偏好，如「经济型酒店」")
    preferences: list[str] = Field(default_factory=list, description="旅行偏好标签")
    free_text_input: str = Field(default="", description="额外要求的自由文本")

    @field_validator("start_date", "end_date")
    @classmethod
    def _check_date_format(cls, value: str) -> str:
        """校验日期为 YYYY-MM-DD 格式，非法则抛错（FastAPI 转 422）。"""
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"日期格式必须为 YYYY-MM-DD，收到: {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _check_date_order(self) -> "TripRequest":
        if self.start_date > self.end_date:
            raise ValueError(
                f"开始日期 {self.start_date} 不能晚于结束日期 {self.end_date}"
            )
        return self


class Attraction(BaseSchema):
    """景点信息（对应前端 Attraction，除 name 外均可选）。"""

    name: str = Field(..., min_length=1, description="景点名称")
    address: str | None = Field(default=None, description="地址")
    location: Location | None = Field(default=None, description="经纬度坐标")
    visit_duration: int | None = Field(default=None, ge=0, description="建议游览时长（分钟）")
    description: str | None = Field(default=None, description="景点描述")
    ticket_price: int | None = Field(default=None, ge=0, description="门票价格（元）")


class Meal(BaseSchema):
    """餐饮信息（对应前端 Meal）。"""

    type: str = Field(..., description="类型：breakfast/lunch/dinner/snack 等")
    name: str = Field(..., min_length=1, description="餐饮名称")
    description: str | None = Field(default=None, description="描述")
    estimated_cost: int | None = Field(default=None, ge=0, description="预估费用（元）")


class DayPlan(BaseSchema):
    """单日行程（对应前端 DayPlan）。"""

    date: str = Field(..., description="日期 YYYY-MM-DD")
    day_index: int = Field(..., ge=0, description="第几天（从 0 开始）")
    description: str = Field(..., description="当日行程描述")
    transportation: str | None = Field(default=None, description="当日交通方式")
    accommodation: str | None = Field(default=None, description="当日住宿")
    attractions: list[Attraction] = Field(default_factory=list, description="景点列表")
    meals: list[Meal] = Field(default_factory=list, description="餐饮列表")


class Budget(BaseSchema):
    """预算汇总（对应前端 budget，全部可选）。"""

    total: int | None = Field(default=None, ge=0, description="总费用（元）")
    total_attractions: int | None = Field(default=None, ge=0, description="门票合计")
    total_hotels: int | None = Field(default=None, ge=0, description="住宿合计")
    total_meals: int | None = Field(default=None, ge=0, description="餐饮合计")
    total_transportation: int | None = Field(default=None, ge=0, description="交通合计")


class TripPlan(BaseSchema):
    """旅行计划（对应前端 TripPlan）。"""

    city: str = Field(..., description="目的地城市")
    start_date: str = Field(..., description="开始日期")
    end_date: str = Field(..., description="结束日期")
    days: list[DayPlan] = Field(..., description="每日行程")
    overall_suggestions: str | None = Field(default=None, description="总体建议")
    budget: Budget | None = Field(default=None, description="预算汇总")


class TripPlanResponse(BaseSchema):
    """旅行规划响应信封（对应前端 TripPlanResponse）。"""

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="提示信息")
    data: TripPlan | None = Field(default=None, description="旅行计划（失败时为 None）")
