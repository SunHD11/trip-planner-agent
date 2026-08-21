"""Step 8 验收：Agent 主循环测试（FakeLLM + stub 服务，零 token 消耗）。

覆盖场景：
1. 工具循环机制：tool_calls → handler → tool 消息回填（tool_call_id 对齐）
2. JSON 校验失败 → LLM 修正重试成功
3. 重试仍失败 → fallback 兜底
4. 循环耗尽 → fallback
5. 未知工具 → error 回填而非崩溃
6. LLM 抛错 → fallback
7. extract_json 三级提取策略
"""

import json
from dataclasses import dataclass, field

import pytest

import app.agent.tools.amap_tools as amap_tools
import app.agent.trip_planner as trip_planner
from app.agent.trip_planner import (
    JsonExtractionError,
    SimpleTripPlannerAgent,
    _assistant_message_to_dict,
    _create_fallback_plan,
    extract_json,
    get_trip_planner_agent,
)
from app.core.llm import LLMError
from app.schemas.common import Location
from app.schemas.map import POIInfo
from app.schemas.trip import TripPlan, TripRequest

REQUEST = TripRequest(
    city="北京",
    start_date="2026-09-01",
    end_date="2026-09-01",
    transportation="公共交通",
    accommodation="经济型酒店",
    preferences=["历史文化"],
)

VALID_PLAN_JSON = json.dumps(
    {
        "city": "北京",
        "start_date": "2026-09-01",
        "end_date": "2026-09-01",
        "days": [
            {
                "date": "2026-09-01",
                "day_index": 0,
                "description": "故宫一日游",
                "transportation": "公共交通",
                "accommodation": "经济型酒店",
                "attractions": [
                    {
                        "name": "故宫博物院",
                        "address": "景山前街4号",
                        "location": {"longitude": 116.397, "latitude": 39.916},
                        "visit_duration": 180,
                        "description": "明清皇宫",
                        "ticket_price": 60,
                    }
                ],
                "meals": [
                    {"type": "breakfast", "name": "庆丰包子铺", "estimated_cost": 20},
                    {"type": "lunch", "name": "四季民福", "estimated_cost": 120},
                    {"type": "dinner", "name": "东来顺", "estimated_cost": 150},
                ],
            }
        ],
        "overall_suggestions": "天气晴好，注意防晒。",
        "budget": {
            "total_attractions": 60,
            "total_hotels": 0,
            "total_meals": 290,
            "total_transportation": 10,
            "total": 360,
        },
    },
    ensure_ascii=False,
)


# ============ FakeLLM：按剧本返回消息 ============


@dataclass(frozen=True)
class FakeFunction:
    name: str
    arguments: str


@dataclass(frozen=True)
class FakeToolCall:
    id: str
    function: FakeFunction


@dataclass(frozen=True)
class FakeMessage:
    content: str | None = None
    tool_calls: list[FakeToolCall] | None = None


@dataclass
class FakeLLM:
    """脚本化 LLM：依次返回预设消息，并记录每次调用看到的 messages。"""

    script: list[FakeMessage] = field(default_factory=list)
    error: Exception | None = None
    calls: list[list[dict]] = field(default_factory=list)

    def chat(self, messages: list[dict], tools: list | None = None, temperature: float = 0.0):
        self.calls.append([dict(m) for m in messages])
        if self.error is not None:
            raise self.error
        if not self.script:
            raise AssertionError("FakeLLM 剧本已耗尽")
        return self.script.pop(0)


class StubAmapService:
    """最小服务桩：只支撑 search_poi 一条链路。"""

    async def search_poi(self, keywords: str, city: str, limit: int = 10) -> list[POIInfo]:
        return [
            POIInfo(
                id="B000A7O1CU",
                name="故宫博物院",
                type="风景名胜;景点",
                address="景山前街4号",
                location=Location(longitude=116.397, latitude=39.916),
            )
        ]


@pytest.fixture
def stub_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(amap_tools, "get_amap_service", lambda: StubAmapService())


# ============ 场景 1：工具循环机制 ============


async def test_tool_loop_executes_handler_and_echoes_tool_call_id(stub_service: None) -> None:
    tool_call = FakeToolCall(id="call_abc123", function=FakeFunction(
        name="search_poi", arguments='{"keywords": "故宫", "city": "北京"}'
    ))
    fake_llm = FakeLLM(script=[
        FakeMessage(content=None, tool_calls=[tool_call]),
        FakeMessage(content=f"```json\n{VALID_PLAN_JSON}\n```"),
    ])
    plan = await SimpleTripPlannerAgent(llm=fake_llm).plan(REQUEST)

    assert isinstance(plan, TripPlan)
    assert plan.city == "北京"
    assert plan.days[0].attractions[0].name == "故宫博物院"
    # 第 2 次 LLM 调用看到的消息序列：system, user, assistant(tool_calls), tool
    second_call = fake_llm.calls[1]
    assert [m["role"] for m in second_call] == ["system", "user", "assistant", "tool"]
    assistant_msg = second_call[2]
    assert assistant_msg["tool_calls"][0]["id"] == "call_abc123"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "search_poi"
    tool_msg = second_call[3]
    assert tool_msg["tool_call_id"] == "call_abc123"  # id 必须原样回填
    assert "故宫博物院" in tool_msg["content"]  # handler 真实执行了


async def test_unknown_tool_returns_error_message_not_crash(stub_service: None) -> None:
    fake_llm = FakeLLM(script=[
        FakeMessage(content=None, tool_calls=[FakeToolCall(
            id="call_x", function=FakeFunction(name="fly_to_moon", arguments="{}")
        )]),
        FakeMessage(content=VALID_PLAN_JSON),
    ])
    plan = await SimpleTripPlannerAgent(llm=fake_llm).plan(REQUEST)
    assert isinstance(plan, TripPlan)
    tool_msg = fake_llm.calls[1][3]
    assert "未知工具" in tool_msg["content"]


# ============ 场景 2/3：JSON 校验重试 ============


async def test_validation_retry_then_success(stub_service: None) -> None:
    invalid_json = json.dumps({"city": "北京"})  # 缺 days，必失败
    fake_llm = FakeLLM(script=[
        FakeMessage(content=invalid_json),
        FakeMessage(content=VALID_PLAN_JSON),
    ])
    plan = await SimpleTripPlannerAgent(llm=fake_llm).plan(REQUEST)
    assert plan.days[0].meals[1].name == "四季民福"
    # 修正请求作为 user 消息追加，包含错误说明
    retry_prompt = fake_llm.calls[1][-1]
    assert retry_prompt["role"] == "user"
    assert "未通过校验" in retry_prompt["content"]


async def test_validation_failure_after_retry_falls_back(stub_service: None) -> None:
    fake_llm = FakeLLM(script=[
        FakeMessage(content="这不是 JSON"),
        FakeMessage(content="还是不是 JSON"),
    ])
    plan = await SimpleTripPlannerAgent(llm=fake_llm).plan(REQUEST)
    assert "暂时不可用" in (plan.overall_suggestions or "")
    assert len(plan.days) == 1
    assert len(fake_llm.calls) == 2  # 首次 + 修正一次，不再更多


# ============ 场景 4：循环耗尽 ============


async def test_loop_exhaustion_falls_back(stub_service: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trip_planner, "MAX_ITERATIONS", 3)
    tool_call = FakeToolCall(id="call_loop", function=FakeFunction(
        name="search_poi", arguments='{"keywords": "故宫", "city": "北京"}'
    ))
    fake_llm = FakeLLM(script=[FakeMessage(content=None, tool_calls=[tool_call]) for _ in range(5)])
    plan = await SimpleTripPlannerAgent(llm=fake_llm).plan(REQUEST)
    assert len(fake_llm.calls) == 3  # 硬上限生效
    assert len(plan.days) == 1
    assert "暂不可用" in plan.days[0].description


# ============ 场景 5：LLM 抛错 → fallback ============


async def test_llm_error_falls_back_without_raising(stub_service: None) -> None:
    fake_llm = FakeLLM(error=LLMError("connection timeout"))
    plan = await SimpleTripPlannerAgent(llm=fake_llm).plan(REQUEST)
    assert isinstance(plan, TripPlan)
    assert plan.city == "北京"
    assert "暂时不可用" in (plan.overall_suggestions or "")


def test_agent_satisfies_protocol() -> None:
    from app.agent.base import TripPlannerAgent

    assert isinstance(SimpleTripPlannerAgent(llm=FakeLLM()), TripPlannerAgent)


# ============ 场景 6：extract_json 三级策略 ============


def test_extract_json_from_json_fence() -> None:
    assert extract_json(f"前言\n```json\n{VALID_PLAN_JSON}\n```\n后记")["city"] == "北京"


def test_extract_json_from_plain_fence() -> None:
    assert extract_json('```\n{"a": 2}\n```') == {"a": 2}


def test_extract_json_from_bare_braces() -> None:
    assert extract_json('噪音 {"a": 3} 噪音') == {"a": 3}


def test_extract_json_unclosed_fence() -> None:
    assert extract_json('```json\n{"a": 4}') == {"a": 4}


def test_extract_json_no_content_raises() -> None:
    with pytest.raises(JsonExtractionError):
        extract_json("完全没有 JSON 的一段话")


def test_extract_json_malformed_raises() -> None:
    with pytest.raises(JsonExtractionError):
        extract_json('{"a": broken}')


def test_extract_json_non_object_raises() -> None:
    with pytest.raises(JsonExtractionError):
        extract_json("[1, 2, 3]")


def test_extract_json_empty_raises() -> None:
    with pytest.raises(JsonExtractionError):
        extract_json("")


# ============ fallback 结构与消息转换 ============


def test_fallback_plan_structure() -> None:
    three_days = REQUEST.model_copy(update={"end_date": "2026-09-03"})
    plan = _create_fallback_plan(three_days)
    assert [d.date for d in plan.days] == ["2026-09-01", "2026-09-02", "2026-09-03"]
    assert [d.day_index for d in plan.days] == [0, 1, 2]
    for day in plan.days:
        assert len(day.attractions) == 2
        assert [m.type for m in day.meals] == ["breakfast", "lunch", "dinner"]
        assert day.transportation == REQUEST.transportation
        assert day.accommodation == REQUEST.accommodation


def test_assistant_message_to_dict_minimal_keys() -> None:
    message = FakeMessage(content=None, tool_calls=[FakeToolCall(
        id="call_1", function=FakeFunction(name="get_weather", arguments='{"city": "北京"}')
    )])
    payload = _assistant_message_to_dict(message)
    assert set(payload.keys()) == {"role", "content", "tool_calls"}
    assert payload["tool_calls"][0] == {
        "id": "call_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city": "北京"}'},
    }


def test_assistant_message_without_tool_calls() -> None:
    payload = _assistant_message_to_dict(FakeMessage(content="最终答案"))
    assert payload == {"role": "assistant", "content": "最终答案"}


def test_get_trip_planner_agent_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(trip_planner, "_planner", None)
    sentinel = SimpleTripPlannerAgent(llm=FakeLLM())
    monkeypatch.setattr(trip_planner, "SimpleTripPlannerAgent", lambda: sentinel)
    assert get_trip_planner_agent() is sentinel
    assert get_trip_planner_agent() is sentinel  # 第二次命中缓存
