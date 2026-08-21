"""通用数据模型：地理位置与统一 API 响应信封。"""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class BaseSchema(BaseModel):
    """所有 schema 的基类。

    frozen=True 使模型实例不可变：任何原地修改都会抛异常，
    需要"修改"时请用 model_copy(update=...) 生成新实例。
    """

    model_config = ConfigDict(frozen=True)


class Location(BaseSchema):
    """地理位置坐标（高德返回的 "lng,lat" 字符串拆分后的结果）。"""

    longitude: float = Field(..., description="经度")
    latitude: float = Field(..., description="纬度")


class ApiResponse(BaseSchema, Generic[T]):
    """统一 API 响应信封：{success, message, data}。

    与前端约定一致：前端按信封里的 success 判断成败，
    失败时 data 为 None、message 携带可读错误信息。
    """

    success: bool = Field(..., description="是否成功")
    message: str = Field(default="", description="提示信息")
    data: T | None = Field(default=None, description="响应数据（失败时为 None）")
