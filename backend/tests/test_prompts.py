"""Step 7 验收：提示词模块测试。"""

from app.agent.prompts.trip_planner import TRIP_PLANNER_SYSTEM_PROMPT, build_user_message
from app.schemas.trip import TripRequest

REQUEST = TripRequest(
    city="北京",
    start_date="2026-09-01",
    end_date="2026-09-03",
    transportation="公共交通",
    accommodation="经济型酒店",
    preferences=["历史文化", "美食"],
    free_text_input="希望多安排博物馆",
)


def test_prompt_references_all_tools() -> None:
    """system prompt 必须提及全部 4 个工具，模型才知道怎么用。"""
    for tool_name in ("search_poi", "get_weather", "plan_route", "geocode"):
        assert tool_name in TRIP_PLANNER_SYSTEM_PROMPT


def test_prompt_contains_output_contract() -> None:
    """输出格式约定必须与 TripPlan 关键字段一致。"""
    for key in ("day_index", "attractions", "meals", "overall_suggestions", "budget"):
        assert key in TRIP_PLANNER_SYSTEM_PROMPT


def test_build_user_message_contains_all_fields() -> None:
    message = build_user_message(REQUEST)
    assert "北京" in message
    assert "2026-09-01" in message and "2026-09-03" in message
    assert "共 3 天" in message  # 天数自动推算
    assert "公共交通" in message
    assert "经济型酒店" in message
    assert "历史文化、美食" in message
    assert "希望多安排博物馆" in message


def test_build_user_message_without_extra_input() -> None:
    minimal = REQUEST.model_copy(update={"free_text_input": "", "preferences": []})
    message = build_user_message(minimal)
    assert "额外要求" not in message
    assert "无（可自由发挥）" in message
