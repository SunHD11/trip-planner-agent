# 单 Agent 旅行助手 · 逐步实施手册

> 决策：不使用 hello-agents 框架，采用「单 Agent + 原生 function calling」方案。
> 本手册按 Step 0 → 11 顺序执行，每步有「完成标准」，不达标不进下一步。
> 预估工作量：约 7~8 天（业余）/ 4 天（全天），关键路径 Step 3 → 5 → 6 → 8。

## 总体架构（先看懂再动手）

```
POST /api/trip/plan
   │
   ▼
routes/trip.py
   │  调用接口
   ▼
TripPlannerAgent.plan(request)          ◄── 核心循环（Step 8）
   │
   │  messages = [system, user]
   │  ┌────────────── 循环 ≤10 轮 ──────────────┐
   │  │ ① llm.chat(messages, tools=工具定义)     │
   │  │ ② 响应带 tool_calls？                    │
   │  │    ├─ 是 → 执行工具 → 结果回填 messages  │
   │  │    └─ 否 → 得到最终 JSON 文本，出循环    │
   │  └─────────────────────────────────────────┘
   │
   ├── tools/amap_tools.py（工具注册表，Step 6）
   │        │ 每个工具 handler 转调 ↓
   │        ▼
   │   services/amap_service.py（高德 REST 客户端，Step 3）
   │
   ▼
提取 JSON → TripPlan 校验 → 失败重试1次 → 仍失败走兜底
```

一次真实对话的消息序列（理解全局的关键）：

```
[system]    你是旅行规划师…必须用工具查真实数据…最终输出JSON…
[user]      请为「北京 2026-09-01 ~ 2026-09-03，公共交通，经济型酒店，偏好:历史文化」规划行程
[assistant] tool_calls: [search_poi(keywords="历史文化", city="北京")]
[tool]      {"pois":[{"name":"故宫博物院","address":"…","location":{…}}, …]}
[assistant] tool_calls: [get_weather(city="北京")]
[tool]      {"forecasts":[{"date":"2026-09-01","day_weather":"晴",…}, …]}
[assistant] tool_calls: [search_poi(keywords="经济型酒店", city="北京")]
[tool]      {"pois":[…]}
[assistant] （无 tool_calls）```json {"city":"北京","days":[…]} ```   ← 最终答案
```

## 目录结构（已建好骨架）

```
backend/
├── app/
│   ├── config.py                        Step 2
│   ├── main.py                          Step 9
│   ├── api/
│   │   ├── router.py                    Step 9
│   │   └── routes/
│   │       ├── health.py                Step 9
│   │       ├── trip.py                  Step 9
│   │       └── map.py                   Step 9
│   ├── schemas/
│   │   ├── common.py                    Step 1
│   │   ├── trip.py                      Step 1
│   │   └── map.py                       Step 1
│   ├── services/
│   │   └── amap_service.py              Step 3
│   ├── agent/                           ★ 核心工作
│   │   ├── base.py                      Step 8
│   │   ├── trip_planner.py              Step 8
│   │   ├── tools/amap_tools.py          Step 6
│   │   └── prompts/trip_planner.py      Step 7
│   └── core/
│       ├── llm.py                       Step 0 迁移 + Step 4 扩展
│       └── logging.py                   Step 9
├── tests/                               Step 11
├── pyproject.toml                       Step 0
└── .env.example                         Step 0
```

---

## Step 0 · 依赖与迁移（0.5 天）✅ 已完成（2026-08-21）

- [x] `pyproject.toml` 增加依赖：`fastapi`、`uvicorn[standard]`、`pydantic-settings`、`httpx`；开发依赖：`pytest`、`pytest-asyncio`、`pytest-cov`
- [x] 执行 `uv sync`
- [x] 把旧 `backend/core/llm.py` **移动**到 `app/core/llm.py`（内容先不改），删除旧 `backend/core/` 目录
- [x] 新建 `backend/.env.example`：字段与 `.env` 相同但全部用占位符（`your-key-here`）

**完成标准：** `uv run python -c "import fastapi, httpx, pydantic_settings"` 无报错；旧 `core/` 目录消失。

---

## Step 1 · 数据契约 schemas（0.5 天）✅ 已完成（2026-08-21，17/17 测试通过）

**文件 1：`app/schemas/common.py`**
- `Location`：`longitude: float`、`latitude: float`
- 泛型响应信封 `ApiResponse`：`success: bool`、`message: str`、`data: Optional[T]`

**文件 2：`app/schemas/trip.py`** —— 严格镜像前端 `types/trip.ts`，字段名一个都不能差：

| 模型 | 字段（✓必填 / ○可选） |
|---|---|
| `TripRequest` | ✓city ✓start_date ✓end_date ✓transportation ✓accommodation ○preferences(默认[]) ○free_text_input(默认"") |
| `Attraction` | ✓name ○address ○location ○visit_duration(int,分钟) ○description ○ticket_price(int) |
| `Meal` | ✓type ✓name ○description ○estimated_cost(int) |
| `DayPlan` | ✓date ✓day_index ✓description ○transportation ○accommodation ✓attractions[] ✓meals[] |
| `Budget` | 全部可选：total / total_attractions / total_hotels / total_meals / total_transportation |
| `TripPlan` | ✓city ✓start_date ✓end_date ✓days[] ○overall_suggestions ○budget |
| `TripPlanResponse` | ✓success ✓message ○data(TripPlan) |

另外：
- `TripRequest` 上校验 `start_date <= end_date`、日期格式 `YYYY-MM-DD`（Pydantic 字段校验，不合法直接 422）
- 提供工具函数 `calc_travel_days(start, end) -> int`，agent 层要用

**文件 3：`app/schemas/map.py`**
- `POIInfo`：id / name / type / address / location / ○tel
- `WeatherInfo`：date / day_weather / night_weather / day_temp / night_temp / wind_direction / wind_power（温度字段加 before 校验器，把 `"25°C"` 清洗成 int——参考原仓库写法）
- `RouteInfo`：distance(米) / duration(秒) / route_type / description
- `POISearchResponse / WeatherResponse / RouteResponse`，套 `ApiResponse` 信封

**自测：** `tests/test_schemas.py`：手写样例 JSON `model_validate` 一遍；非法日期被拒。

**完成标准：** 测试全绿；`TripPlan` 字段与前端 ts 类型逐一比对无差异。

---

## Step 2 · 配置 config.py（0.5 天，可与 Step 1 并行）✅ 已完成（2026-08-21，24/24 测试通过）

**文件：`app/config.py`**，pydantic-settings：

| 字段 | 类型 | 必填 | 对应 .env |
|---|---|---|---|
| `llm_model_id` | str | ✅ | LLM_MODEL_ID |
| `llm_api_key` | str | ✅ | LLM_API_KEY |
| `llm_base_url` | str | ✅ | LLM_BASE_URL |
| `llm_timeout` | int | 默认 60 | LLM_TIMEOUT |
| `amap_api_key` | str | ✅ | AMAP_API_KEY |
| `host` / `port` | str / int | 默认 0.0.0.0 / 8000 | HOST / PORT |
| `cors_origins` | str | 有默认值 | CORS_ORIGINS |
| `log_level` | str | 默认 INFO | LOG_LEVEL |

要点：
- `env_file=".env"`、`extra="ignore"`、大小写不敏感
- `get_cors_origins_list()` 方法把逗号串切成 list
- 模块底部创建全局 `settings` 实例——**缺 key 时 import 即报错**（启动即校验）
- 不写原仓库那种 `validate_config()` 手动检查，pydantic 已替代

**自测：** 临时注释 `.env` 里的 `AMAP_API_KEY`，跑 `uv run python -c "from app.config import settings"`，应立即抛 `ValidationError` 并指明缺哪个字段。改回来。

**完成标准：** 报错实验符合预期。

---

## Step 3 · 高德服务 amap_service.py（1 天）⚠️ 关键路径 ✅ 已完成（2026-08-21，10/10 单测 + 真实 key 四项全通）

**文件：`app/services/amap_service.py`**

### 3.1 基础设施
- 自定义异常 `AmapError(message, info_code)`
- 类 `AmapService`，构造接收 `api_key` 和 `httpx.AsyncClient`（client 创建/关闭交给 main.py 的 lifespan，便于测试注入）
- 私有方法 `_get(path, params) -> dict`：统一加 `key`、发请求、检查 HTTP 状态、检查 `status == "1"`（否则抛 `AmapError`，带 `info`/`infocode`）
- 模块级单例 `get_amap_service()`

### 3.2 五个方法（按顺序实现，每写完一个立刻手动验证）

| # | 方法 | 端点 | 解析要点 |
|---|---|---|---|
| 1 | `geocode(address, city) -> Location + adcode` | `GET https://restapi.amap.com/v3/geocode/geo` | 取 `geocodes[0]`；`location` 是 `"116.397,39.908"` 字符串，按逗号拆成两个 float |
| 2 | `search_poi(keywords, city, limit=10) -> list[POIInfo]` | `GET /v3/place/text`，参数 `keywords, city, citylimit=true, offset=limit` | 遍历 `pois[]`，拆 location；`address`/`tel` 可能是 `[]`，要判类型再取值 |
| 3 | `get_weather(city) -> list[WeatherInfo]` | `GET /v3/weather/weatherInfo`，参数 `city=<adcode>, extensions=all` | ⚠️ **city 必须是 adcode**：内部先 `geocode(city)` 拿 adcode，用 dict 缓存 `{城市名: adcode}`。取 `forecasts[0].casts[]` 映射 |
| 4 | `plan_route(origin_addr, dest_addr, mode, origin_city, dest_city) -> RouteInfo` | 步行 `/v3/direction/walking`；驾车 `/v3/direction/driving`；公交 `/v3/direction/transit/integrated` | ⚠️ **路线 API 只认坐标**：两个地址先各 `geocode`；公交额外需 `city`（起点城市）和 `cityd`（终点城市）。取 `route.paths[0]`（步行/驾车）的 `distance`、`duration`；公交取 `route.distance` 和 `route.taxi_cost` |
| 5 | （可选）分类搜索 | 同 place/text 换 keywords | 暂不做也行 |

### 3.3 手动自测

写临时脚本 `scratch_manual_check.py`（不进 git），用真实 key 依次调：
1. `geocode("北京市朝阳区", "北京")` → 有坐标
2. `search_poi("故宫", "北京")` → 第一条是故宫博物院，坐标约 (116.397, 39.916)
3. `get_weather("北京")` → 返回今天起 3 天预报
4. `plan_route("故宫博物院", "颐和园", "transit", "北京", "北京")` → 有距离和耗时

**完成标准：** 4 个手动调用全部返回真实数据；传错 key 时抛带 `infocode` 的 `AmapError` 而不是裸异常。

> 调用失败排查：确认 key 是「Web 服务」类型（高德控制台 → 应用管理 → 查看 key 的服务平台）。这是最常见卡点。

---

## Step 4 · 扩展 LLM 客户端（0.5 天）✅ 已完成（2026-08-21）

**文件：`app/core/llm.py`**。现有 `think()` 保留，**新增 `chat()`**：

- 签名：`chat(messages, tools=None, temperature=0) -> 消息对象`
- 与 `think()` 的三个本质区别：
  1. **不开流式**（`stream=False`）。流式 tool_calls 分片到达，拼接复杂，v1 不碰
  2. **返回整个 assistant message**（`response.choices[0].message`），可能带 `content` 也可能带 `tool_calls`，调用方两者都要能拿到
  3. **透传 `tools` 参数**（Step 6 产出的工具定义 list）
- 异常处理：API 报错时抛出带上下文的异常（不要吞错返回 None——循环里拿到 None 极难排查）
- `print` 全部换 `logging`

**自测：** 临时脚本，普通消息调 `chat()` 不带 tools，确认拿到 `message.content`。

**完成标准：** 拿到非流式完整 message 对象。

---

## Step 5 · 最小 tool-calling 冒烟验证（0.5 天）⭐ 风险拦截点 ✅ 已通过（2026-08-21，deepseek-v4-flash 确认支持 function calling，无需换模型）

**写任何真实工具之前**，先验证「模型 + OpenAI SDK + tool_calls」链路。

- 临时脚本定义假工具：名字 `get_current_time`，描述「获取当前时间」，参数为空对象
- 消息：user 问「现在几点了？」
- 调 `llm.chat(messages, tools=[假工具定义])`
- 检查 `message.tool_calls` 非空，打印 `tool_calls[0].function.name` 和 `arguments`

**三种结果：**
- ✅ 返回 tool_calls → 链路通，继续
- ❌ 模型直接文本回答、没调工具 → 换支持 function calling 的模型 id（DeepSeek 用 `deepseek-chat`；确认 .env 里的模型名），或 system prompt 强调必须使用工具
- ❌ API 不识别 tools 参数报错 → 检查 base_url 和 SDK 版本

**完成标准：** 假工具被成功调用，`arguments` 是合法 JSON 字符串。**这一步不通后面全白做，必须先做。**

---

## Step 6 · 工具注册表 agent/tools/amap_tools.py（1 天）✅ 已完成（2026-08-21，11 个 handler 测试通过）

### 6.1 工具定义结构

每个工具四要素：`name`、`description`（给 LLM 看，**写清何时用、参数怎么填**——这是 agent 智商的一半）、`parameters`（JSON Schema）、`handler`（async 函数，转调 amap_service）。

OpenAI 工具定义整体形状（每个工具都套这个壳）：

```
{ "type": "function",
  "function": { "name": …, "description": …, "parameters": {JSON Schema} } }
```

### 6.2 注册的 4 个工具

| 工具名 | 参数 | handler 行为 | 返回给 LLM 的内容（精简 JSON 字符串） |
|---|---|---|---|
| `search_poi` | keywords✓, city✓ | `amap_service.search_poi` | ≤10 条，每条只留 `name / address / location / type` |
| `get_weather` | city✓ | `amap_service.get_weather` | 未来几天预报数组 |
| `plan_route` | origin✓, destination✓, mode(枚举 walking/driving/transit，默认 walking), ○city | `amap_service.plan_route` | `{distance_m, duration_s, mode}` |
| `geocode` | address✓, ○city | `amap_service.geocode` | 单个坐标 + adcode |

### 6.3 三条铁律（handler 实现规范）

1. **handler 永远返回字符串，永不抛异常**。内部 try/except，失败返回 `{"error": "错误描述"}`——错误回填给 LLM 让它换姿势重试，而不是崩掉循环
2. **参数解析要防御**：`arguments` 是 JSON 字符串，`json.loads` 可能失败、可能缺参数，都按「返回 error JSON 字符串」处理
3. **结果要裁剪**：高德原始响应很大，回填前只留必要字段、限制条数（POI ≤10）。token 是钱，也影响模型注意力

### 6.4 注册表

模块维护 `dict[str, handler]`（名字 → 执行函数）和 `TOOL_SCHEMAS`（定义列表），导出这两个。

**自测：** 临时脚本直接调 handler（不经 LLM）：`await search_poi_handler('{"keywords":"故宫","city":"北京"}')` 返回精简 JSON；故意传错参数，确认返回 error JSON 而非抛异常。

**完成标准：** 4 个 handler 手动调通 + 1 个错误用例返回 error JSON。

---

## Step 7 · 系统提示词 agent/prompts/trip_planner.py（0.5 天）✅ 已完成（2026-08-21，4 个提示词测试通过）

模块级常量 `TRIP_PLANNER_SYSTEM_PROMPT`，分五段：

1. **角色**：专业旅行规划师，擅长基于真实地理数据安排行程
2. **工作流程要求**（最关键）：
   - 必须先用 `search_poi` 按用户偏好分类搜索景点（每个偏好搜一次）
   - 必须用 `get_weather` 查询行程日期内的天气
   - 用 `search_poi`（keywords=住宿偏好+「酒店」）查住宿
   - 景点 `location` 坐标**必须来自工具返回结果，禁止编造**
   - 数据收集充分后一次性输出完整 JSON，不分段
3. **行程安排规则**：每天 2~3 个景点；按地理位置就近安排（同一天景点应在同一区域）；每天早中晚三餐；交通方式尊重用户选择
4. **输出格式**：与 `TripPlan` 完全一致的 JSON 结构示例（把 Step 1 字段结构贴进来当模板），强调：只输出 JSON、温度/价格必须是纯数字、`day_index` 从 0 开始
5. **预算要求**：汇总门票、住宿、餐饮、交通四项到 budget

另备**构建 user 消息的函数** `build_user_message(request, travel_days)`：把 TripRequest 字段格式化成需求描述文本（城市、日期区间、天数、交通、住宿、偏好列表、额外要求）。

**完成标准：** 通读一遍，把自己当成模型，检查有无歧义。

---

## Step 8 · Agent 主体 agent/trip_planner.py（1.5~2 天）⭐ 核心 ✅ 已完成（2026-08-21，19 个 mock 测试全绿 + 真实端到端产出北京 3 日游行程）

### 8.1 接口 `agent/base.py`

`Protocol`（或抽象基类）`TripPlannerAgent`，唯一方法签名：

```
async plan(request: TripRequest) -> TripPlan
```

HTTP 层只 import 接口 + 工厂函数，永不直接 import 实现类——保障未来随意重构 agent 内部。

### 8.2 实现类 `SimpleTripPlannerAgent`

构造：接收 `llm`（core/llm.py 客户端）和工具注册表。

`plan()` 完整流程，**逐条照做**：

**① 组装初始消息**
- `[{"role": "system", "content": TRIP_PLANNER_SYSTEM_PROMPT}, {"role": "user", "content": build_user_message(...)}]`

**② 主循环**（`for _ in range(MAX_ITERATIONS=10)`）
1. 调 `llm.chat(messages, tools=TOOL_SCHEMAS)`
2. 拿到 `message`，**先把这个 assistant message 原样追加进 messages**（带 tool_calls 的 assistant 消息必须完整回填，否则下轮对话格式非法）
3. 判断 `message.tool_calls`：
   - **有** → 遍历每个 tool_call：
     - 取 `function.name` 和 `function.arguments`
     - 查注册表找 handler；找不到 → 结果写 `{"error": "未知工具: xxx"}`
     - 执行 handler 拿结果字符串
     - 追加 tool 消息：**`{"role": "tool", "tool_call_id": <该 tool_call 的 id>, "content": <结果字符串>}`** —— `tool_call_id` 必须原样带回，OpenAI 协议硬性要求
     - 继续下一轮循环
   - **没有** → `message.content` 即最终答案，记下，`break`
4. 跑满 10 轮仍无最终答案 → 记日志，走 fallback

**③ JSON 提取**（工具函数 `extract_json(text) -> dict`）
按优先级：先找 ```json …``` 围栏 → 普通 ``` 围栏 → 第一个 `{` 到最后一个 `}` 的子串；`json.loads`；全失败抛自定义异常。

**④ 校验与重试**
- `TripPlan.model_validate(提取出的 dict)`
- 成功 → 返回
- 失败（`ValidationError`）→ 追加 user 消息：「JSON 未通过校验，错误如下：<可读错误文本>。请输出修正后的完整 JSON」，**再调一次 LLM**（可不带 tools），再走 ③④。只重试 1 次。

**⑤ Fallback**
仍失败 → 兜底计划：按日期生成 N 天骨架（每天 2 个占位景点 + 三餐 + 描述文案），`overall_suggestions` 说明「智能规划暂时不可用，已生成基础行程」。保证前端永远拿到合法结构。参考原仓库 `_create_fallback_plan`，字段对齐自己的 schemas。

**⑥ 单例工厂**
`get_trip_planner_agent()`，模块级缓存。

### 8.3 调试利器（强烈建议）

每轮循环用 logging 输出：第几轮、LLM 决定调了哪些工具、每个工具返回的前 200 字符。agent 出问题时这份日志是唯一的朋友。

### 8.4 分层自测（不要一上来跑全流程）

1. **Mock 测循环机制**：pytest 伪造 llm：第一轮返回带 tool_calls 的消息，第二轮返回纯 JSON。断言：handler 被调用、tool 消息带正确 `tool_call_id`、最终拿到 TripPlan。**零 token 成本**，专测循环逻辑
2. **Mock 测重试**：第一轮坏 JSON，第二轮好 JSON。断言重试生效
3. **Mock 测 fallback**：永远坏 JSON。断言兜底计划结构合法
4. **真实调用**：北京 3 日游，盯日志看完整工具链；产出的 TripPlan 打印人工检查（景点真假、坐标格式、三餐齐全）

**完成标准：** 3 个 mock 测试全绿 + 真实调用产出肉眼合格。

---

## Step 9 · API 接线（0.5 天）✅ 已完成（2026-08-21，12 个 TestClient 测试全绿 + 真实启动四接口全通）

1. `app/core/logging.py`：按 settings.log_level 配置根 logger
2. `app/main.py`：
   - 创建 FastAPI（title/version/description）
   - CORS 中间件：origins 从 `settings.get_cors_origins_list()`
   - **lifespan**：启动时创建 `httpx.AsyncClient` 注入 amap_service，关闭时 `aclose()`
   - 全局异常处理器：`AmapError` → 502 + 信封格式；未知异常 → 500 + 信封格式（不向前端泄漏堆栈）
3. `app/api/routes/health.py`：`GET /health` 返回 `{"status": "healthy"}`（前端 api.ts 的约定）
4. `app/api/routes/map.py`：三个接口直调 amap_service（不经 agent）：
   - `GET /api/map/poi?keywords=&city=`
   - `GET /api/map/weather?city=`
   - `POST /api/map/route`（body：起点/终点/方式）
5. `app/api/routes/trip.py`：
   - `POST /api/trip/plan` → `agent = get_trip_planner_agent()` → `plan = await agent.plan(request)` → 包进 `TripPlanResponse(success=True, message="...", data=plan)`
   - agent 抛异常 → `TripPlanResponse(success=False, message=错误信息, data=None)`，HTTP 仍 200（前端按信封 success 判断）
6. `app/api/router.py`：聚合子路由；main.py 挂 `/api` 前缀（health 挂根路径）

**自测：** `uvicorn app.main:app --reload` → `/docs`：health ✓、map/poi ✓、trip/plan 真实规划一遍。

**完成标准：** Swagger 里三个接口全部返回真实数据。

---

## Step 10 · 前后端联调（0.5 天）✅ 已完成（2026-08-21，Vite 代理联调全通 + 类型检查零错误）

1. 后端 8000，前端 `npm run dev` 5173（确认前端 `.env` 的 `VITE_API_BASE_URL=http://localhost:8000`）
2. 提交「北京 3 日游」，检查：
   - 请求体与 `TripRequest` 一致
   - 页面渲染行程卡片（景点、三餐、预算）
   - agent 耗时 >30s 时确认前端 fetch 没被掐断（原生 fetch 无默认超时，一般没问题）
3. 看后端日志，确认工具调用链符合预期

**完成标准：** 页面无报错渲染完整计划，连跑 3 次不同城市都成功。

---

## Step 11 · 测试收尾（1 天）✅ 已提前完成（测试 80 个全绿、覆盖率 87% 超标 + README 完成）

| 测试文件 | 覆盖内容 |
|---|---|
| `tests/test_schemas.py` | 契约校验（Step 1 已写） |
| `tests/test_api.py` | ✅ 已提前完成（Step 9）：TestClient 打 /health、/api/map/*、/api/trip/plan，含 502/500 信封与 422 分支 |
| `tests/test_amap_service.py` | mock httpx 响应，测解析（location 拆分、`[]` 型 address、status=0 抛错） |
| `tests/test_trip_planner.py` | Step 8 的三个 mock 场景 |
| `tests/test_trip_api.py` | ✅ 已并入 `tests/test_api.py`（StubAgent 测信封与违约分支） |

**覆盖率**：87%（653 语句 / 83 未覆盖），超标完成（目标 ≥80%）。

**README**：[backend/README.md](../backend/README.md) 已完成，含快速开始、环境变量说明、API 文档、架构图、常见问题、部署指南。

---

## 踩坑总清单（实施时随时对照）

| # | 坑 | 对策 |
|---|---|---|
| 1 | tool_call_id 没带回 → API 报 400 | tool 消息必须带原 id（Step 8②.3） |
| 2 | 带 tool_calls 的 assistant 消息没回填 → 对话格式非法 | 每轮先 append assistant 再 append tool（Step 8②.2） |
| 3 | `tool_call.function.arguments` 是字符串不是 dict | json.loads + 失败防御（Step 6.3） |
| 4 | 模型不调工具、直接编答案 | prompt 强调 + Step 5 先验证模型能力 |
| 5 | 模型输出 JSON 带围栏/解释文字 | extract_json 三级提取（Step 8③） |
| 6 | 高德天气只认 adcode | service 内部 geocode 转换 + 缓存（Step 3.2） |
| 7 | 高德路线只认坐标 | service 内部先 geocode（Step 3.2） |
| 8 | 高德字段可能是 `[]` 而不是字符串 | 解析时判类型（Step 3.2） |
| 9 | 工具结果太大爆 token | handler 裁剪字段和条数（Step 6.3） |
| 10 | agent 死循环烧 token | MAX_ITERATIONS=10 硬上限（Step 8②） |
| 11 | 流式 + tool_calls 混用 | v1 全程非流式（Step 4） |

---

## 开工顺序

Step 0 → 1 → 2 → 3（手动验证通过）→ 4 → 5（冒烟通过）→ 6 → 7 → 8 → 9 → 10 → 11
