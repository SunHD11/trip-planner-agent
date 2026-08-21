# 智能旅行助手 - 后端服务

基于**单 Agent + OpenAI 原生 function calling**的旅行规划服务，数据源高德地图 Web 服务 API。

## 技术栈

- **FastAPI** 0.115+ — 现代 Python Web 框架
- **Pydantic** 2.7+ / **pydantic-settings** — 类型化配置与数据校验
- **httpx** — 异步 HTTP 客户端（调用高德 API）
- **openai** 3.3+ — OpenAI 兼容接口客户端（支持 DeepSeek、Kimi 等）
- **uv** — 包管理器（比 pip 快 10-100 倍）
- **pytest** + **pytest-asyncio** — 测试框架（当前 80 个测试全绿，覆盖率 87%）

## 快速开始

### 1. 环境准备

```bash
# 安装 uv（如未安装）
# Windows: PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 克隆仓库并进入后端目录
cd backend
```

### 2. 配置环境变量

复制示例配置并填写真实密钥：

```bash
cp .env.example .env
```

编辑 `.env`（**必填项**）：

```env
# LLM（OpenAI 兼容接口）
LLM_MODEL_ID=deepseek-v4-flash           # 或 gpt-4o、kimi-moonshot-v1 等
LLM_API_KEY=sk-xxxxx                     # 你的 API 密钥
LLM_BASE_URL=https://api.deepseek.com    # 或其他兼容服务地址

# 高德地图 Web 服务 Key（申请地址：https://console.amap.com/dev/key/app）
AMAP_API_KEY=your-amap-web-service-key

# 可选配置
LLM_TIMEOUT=60
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

**重要**：
- `AMAP_API_KEY` 必须是「Web 服务」类型（支持 `/v3/place/text`、`/v3/weather/weatherInfo` 等 REST 接口），不是「Web 端」或「Android/iOS」类型
- `LLM_MODEL_ID` 必须支持 **OpenAI function calling** 格式（verified: deepseek-v4-flash、gpt-4o、kimi-moonshot-v1）

### 3. 安装依赖 & 启动

```bash
# 安装所有依赖（含测试）
uv sync

# 启动服务（开发模式，支持热重载）
uv run uvicorn app.main:app --reload
# 或直接
uv run python -m app.main

# 访问 Swagger API 文档
# 浏览器打开 http://127.0.0.1:8000/docs
```

### 4. 运行测试

```bash
# 全部测试（当前 80 个）
uv run pytest

# 带覆盖率报告
uv run pytest --cov=app --cov-report=term-missing

# 生成 HTML 覆盖率报告
uv run pytest --cov=app --cov-report=html
# 打开 htmlcov/index.html 查看详情
```

## API 接口

| 端点 | 方法 | 说明 | 示例 |
|---|---|---|---|
| `/health` | GET | 健康检查 | `{"status":"healthy"}` |
| `/api/map/poi` | GET | POI 搜索 | `?keywords=故宫&city=北京` |
| `/api/map/weather` | GET | 天气预报 | `?city=北京` |
| `/api/map/route` | POST | 路线规划 | 见下方 |
| `/api/trip/plan` | POST | **旅行规划**（核心接口） | 见下方 |

### 旅行规划示例请求

```bash
curl -X POST http://127.0.0.1:8000/api/trip/plan \
  -H "Content-Type: application/json" \
  -d '{
    "city": "北京",
    "start_date": "2026-09-01",
    "end_date": "2026-09-03",
    "transportation": "公共交通",
    "accommodation": "经济型酒店",
    "preferences": ["历史文化", "美食"],
    "free_text_input": "希望多安排博物馆"
  }'
```

**响应格式**（成功失败都 HTTP 200，看 `success` 字段）：

```json
{
  "success": true,
  "message": "行程规划成功",
  "data": {
    "city": "北京",
    "start_date": "2026-09-01",
    "end_date": "2026-09-03",
    "days": [
      {
        "date": "2026-09-01",
        "day_index": 0,
        "description": "第一天行程概述",
        "attractions": [
          {
            "name": "故宫博物院",
            "address": "景山前街4号",
            "location": {"longitude": 116.397, "latitude": 39.916},
            "visit_duration": 180,
            "ticket_price": 60
          }
        ],
        "meals": [
          {"type": "breakfast", "name": "护国寺小吃", "estimated_cost": 25}
        ]
      }
    ],
    "overall_suggestions": "天气提示、出行贴士等",
    "budget": {"total": 1200, "total_attractions": 300}
  }
}
```

## 项目结构

```
backend/
├── app/
│   ├── agent/
│   │   ├── base.py              # Agent 接口协议（TripPlannerAgent）
│   │   ├── trip_planner.py      # 单 Agent 实现（主循环、重试、fallback）
│   │   ├── tools/
│   │   │   └── amap_tools.py    # 4 个工具 handler + OpenAI 格式 schema
│   │   └── prompts/
│   │       └── trip_planner.py  # system prompt + user message 模板
│   ├── api/
│   │   ├── router.py            # 聚合 /api 前缀的子路由
│   │   └── routes/
│   │       ├── health.py        # GET /health
│   │       ├── map.py           # /api/map/* 三个接口
│   │       └── trip.py          # POST /api/trip/plan
│   ├── core/
│   │   ├── llm.py               # OpenAI 兼容 LLM 客户端
│   │   └── logging.py           # 日志配置
│   ├── services/
│   │   └── amap_service.py      # 高德 REST 客户端（geocode/poi/weather/route）
│   ├── schemas/
│   │   ├── common.py            # Location + ApiResponse 信封
│   │   ├── trip.py              # TripRequest / TripPlan（与前端严格对齐）
│   │   └── map.py               # POI / Weather / Route 数据模型
│   ├── config.py                # pydantic-settings 配置（.env 校验）
│   └── main.py                  # FastAPI 应用入口（CORS + lifespan + 异常处理器）
├── tests/                       # 80 个测试，覆盖率 87%
│   ├── test_schemas.py          # 数据契约校验
│   ├── test_config.py           # 配置启动校验
│   ├── test_amap_service.py     # MockTransport 高德服务测试
│   ├── test_amap_tools.py       # StubService 工具 handler 测试
│   ├── test_prompts.py          # 提示词完整性测试
│   ├── test_trip_planner.py     # FakeLLM agent 主循环测试
│   └── test_api.py              # TestClient 路由层测试
├── .env.example                 # 环境变量模板
├── pyproject.toml               # 依赖与项目配置
└── README.md                    # 本文档
```

## 核心设计

### 1. 单 Agent + 原生 function calling

不依赖框架（如 LangChain、hello-agents），直接使用 OpenAI chat.completions API 的 tools 参数：

```python
# 核心循环（简化）
for _ in range(MAX_ITERATIONS):
    message = llm.chat(messages, tools=TOOL_SCHEMAS)  # 模型决定调什么工具
    messages.append(assistant_message)                # 回填 assistant 消息
    if not message.tool_calls:
        break  # 拿到最终 JSON
    for tool_call in message.tool_calls:
        result = await handler(tool_call.function.arguments)
        messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})
```

### 2. 三层防御（永不崩溃）

1. **工具 handler 永不抛异常**：任何失败（参数非法、API 超限）都返回 `{"error": "..."}` JSON 字符串
2. **JSON 提取三级策略**：```json 围栏 → 普通围栏 → 首尾花括号
3. **校验重试 + 兜底计划**：pydantic 校验失败 → 把错误回给 LLM 修正 1 次 → 仍失败走 fallback（N 天骨架行程）

### 3. 高德 API 三个坑的解决

| 坑 | 表现 | 解法（在 [amap_service.py](app/services/amap_service.py) 中） |
|---|---|---|
| 天气接口只认 adcode | 传城市名报错 | `get_weather()` 内部先 `geocode(city)` 获取 adcode 并缓存 |
| 路线接口只认坐标 | 传地址报错 | `plan_route()` 内部自动地理编码起终点 |
| 字段缺失返回 `[]` | `address` 可能是数组而非字符串 | 统一 `_as_str()` 防御所有字符串字段 |

### 4. 类型安全与启动校验

所有配置字段（LLM_API_KEY、AMAP_API_KEY 等）都是 pydantic-settings 的 **必填项**：

```python
class Settings(BaseSettings):
    llm_api_key: str = Field(..., min_length=1)  # ... 表示必填
    amap_api_key: str = Field(..., min_length=1)
```

启动时（`from app.config import settings`）任何缺失或空值都立即抛 `ValidationError`，而不是运行到一半才崩。

## 常见问题

### Q1: 启动时报 `ValidationError: Field required`

**原因**：`.env` 文件缺失或必填字段为空。

**解法**：
1. 确保 `backend/.env` 存在（复制 `.env.example`）
2. 检查 `LLM_API_KEY`、`AMAP_API_KEY` 等必填字段是否有值
3. 确认 `.env` 文件在 `backend/` 目录（与 `app/` 同级），不是项目根目录

### Q2: 旅行计划返回兜底内容（"智能规划暂不可用"）

**可能原因**：
1. LLM 未调用任何工具（prompt 弱或模型不支持 function calling）
2. LLM 输出 JSON 格式非法（未被三级提取识别）
3. JSON 通过提取但 pydantic 校验失败（字段名/类型错误）

**排查步骤**：
1. 查看后端日志，搜索「第 X 轮: 调用工具」—— 没有说明模型未调工具
2. 检查日志里的 LLM 最终输出，看是否包含 JSON
3. 如果模型是自建，用 `/docs` 的 `/api/trip/plan` 手工提交请求，观察 Swagger 返回的 `message` 字段

### Q3: 高德 API 返回 `CUQPS_HAS_EXCEEDED_THE_LIMIT`

**原因**：QPS 配额耗尽（个人开发者账号默认并发限制较低）。

**解法**：
1. 登录[高德控制台](https://console.amap.com/)查看 Key 的并发配额
2. 等待配额恢复（通常按秒/分钟重置）
3. 升级为企业认证账号以提高配额
4. Agent 已内置容错：单次 QPS 超限会返回 error，模型下轮会重试或调整策略

### Q4: 前端请求后端跨域（CORS）报错

**原因**：前端域名不在 `.env` 的 `CORS_ORIGINS` 白名单内。

**解法**：
1. 编辑 `backend/.env`，确保 `CORS_ORIGINS` 包含前端地址：
   ```env
   CORS_ORIGINS=http://localhost:5173,http://localhost:3000
   ```
2. 重启后端服务
3. 开发环境建议前端使用 Vite 代理模式（配置已内置，无需直连后端）

## 开发建议

1. **本地开发用 `--reload`**：代码改动自动重启，无需手动
2. **查看日志定位问题**：后端每轮工具调用、LLM 响应都有 INFO 日志
3. **先跑测试再提交**：`uv run pytest` 确保没破坏现有逻辑
4. **修改 schema 需同步前端**：[backend/app/schemas/trip.py](app/schemas/trip.py) 与 `frontend/src/types/trip.ts` 必须字段对齐

## 部署

### Docker（推荐）

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 裸机部署

```bash
# 生产环境安装（不含测试依赖）
uv sync --no-dev

# 启动（gunicorn + uvicorn workers）
uv run gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

## 许可证

MIT

## 参考

- [实现指南](../docs/IMPLEMENTATION_GUIDE.md)（详细架构与踩坑清单）
- [高德地图 Web 服务 API](https://lbs.amap.com/api/webservice/summary)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
