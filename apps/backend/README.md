# AICustomerServiceAgent Backend

「角色对话 Agent」后端 —— 让「亚丝娜」角色成为具备记忆能力的 AI Agent（FastAPI + LangChain + PostgreSQL）。

## 技术栈

- Python 3.13 + FastAPI + Uvicorn
- LangChain（Chain 编排：路由 / 轮次分析 / 回答 / 状态更新 / 摘要 / 记忆提取）
- PostgreSQL 16（SQLAlchemy ORM + Alembic 版本化迁移）+ pydantic-settings
- pytest + pytest-asyncio（FakeLLM 注入，无真实 LLM 调用）

## 目录结构

```
app/
├── api/v1/            # API 表现层（chat 端点）
├── services/          # 业务服务（会话窗口、记忆、摘要、上下文、编排）
├── repositories/      # 数据访问层（SQLAlchemy）
├── chains/            # LangChain 链（路由 / 回答 / 摘要 / 提取）
├── core/              # 配置、DB 引擎、LLM 工厂
├── models/            # Pydantic 数据模型
├── prompts/           # Prompt 模板与 PromptBuilder
└── character/asuna/   # 亚丝娜角色资产（人设 / 模式指令）
```

三层单向依赖：`api → services → repositories → core`。

## 快速开始

```bash
# 1. 配置环境变量（复制 .env.example 为 .env，并在 LLM_PROFILES_JSON 中填入可用的 API Key）
cp .env.example .env

# 2. 启动本地 PostgreSQL 16（在仓库根目录执行，统一入口为根目录 docker-compose.yml，asuna/asuna/asuna）
docker compose up -d postgres

# 3. 安装依赖并执行数据库迁移
uv sync
uv run alembic upgrade head

# 4. 启动服务
uv run uvicorn app.main:app --reload --port 8000

# 5. 健康检查
curl http://localhost:8000/health
```

## 数据库

- 运行库为 PostgreSQL 16，连接串由 `DATABASE_URL` 配置（默认 `postgresql+psycopg://asuna:asuna@localhost:5432/asuna`）。
- Schema 唯一真相是 Alembic 迁移链（`migrations/versions/`）：rev1 为 V1 四表 baseline，rev2 为 V2 三张状态表；禁止 `create_all` 建表（单元测试内存 SQLite 属豁免）。
- 存量 SQLite 数据可用 `uv run python -m scripts.migrate_sqlite_to_postgres --source sqlite:///./asuna.db` 一次性搬运（幂等，目标表先清后写）。
- 连接池参数（`DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_RECYCLE` / `DB_POOL_PRE_PING`）见配置项表。

## 核心能力

- **长期记忆**：对话中自动提取用户偏好 / 目标，落库并在后续回答中召回
- **对话摘要**：消息数达到阈值后滚动生成摘要，替换超出窗口的上下文
- **多轮窗口**：保留最近 N 条消息（长度 / 字符双重预算）
- **路由降级**：路由置信度低于阈值时降级为 default 模式

## API

### POST /api/v1/chat/message

流式对话端点，返回 SSE 风格逐行 JSON：

```json
{"delta": "你好"}
{"delta": "呀"}
{"done": true, "session_id": "xxxx"}
```

响应头：`X-Session-Id`、`X-Session-New`（首次会话为 `true`）。

请求体示例：

```json
{ "content": "我喜欢吃寿司", "session_id": "xxxx" }
```

- 不带 `session_id` 时创建新会话
- `content` 为空返回 422
- 通过请求体 `profile_id`（或请求头 `X-LLM-Profile`）选择本次对话的模型 profile；未知 id 在流开始前返回 400；响应头回显实际使用的 `X-LLM-Profile`
- LLM 调用失败时流内返回 `{"detail": "LLM 调用失败"}`

### GET /api/v1/llm/profiles

返回可用模型列表与默认项：

```json
{
  "default": "longcat",
  "profiles": [
    { "id": "longcat", "label": "LongCat (longcat.chat)", "model": "LongCat-2.0", "default": true }
  ]
}
```

## 测试

```bash
uv run pytest             # 全量用例（136 项）
uv run pylint app tests   # 代码检查
```

单元 / e2e 测试通过 `tests/conftest.py` 的 FakeLLM 与内存 SQLite（每用例独立建表），不发起真实 LLM 调用；PostgreSQL 集成测试（`tests/test_db_migration.py`）在本地无 PG 实例时自动 skip（`docker compose up -d` 后重跑即执行）。

## 配置项（app/core/settings.py）

| 配置                          | 默认值      | 说明                                |
| ----------------------------- | ----------- | ----------------------------------- |
| `LLM_PROFILES_JSON`           | -           | 模型 profile 数组（必填字段：id / label / base_url / model / api_key；可选覆盖：max_tokens、temperature、top_p、frequency_penalty、presence_penalty、extra_body_thinking；可选 `extra_body` 对象原样透传请求体顶层——如 OpenRouter 的 `{ "reasoning": { "enabled": true } }`，设置后取代默认 thinking 注入） |
| `DEFAULT_LLM_PROFILE`         | longcat     | 默认 profile id（必须在数组内）      |
| `ANSWER_MAX_TOKENS`           | 60          | 最终回答链的输出上限；路由/分析/记忆等辅助链不受此限制，使用各 profile 的 `max_tokens`（建议 ≥512） |
| `TEMPERATURE` 等              | 见 settings | profile 未指定对应字段时的参数缺省   |
| `DATABASE_URL`                | postgresql+psycopg://asuna:asuna@localhost:5432/asuna | 数据库连接串（sqlite 前缀走测试方言分支） |
| `DB_POOL_SIZE`                | 5           | PG 连接池大小                       |
| `DB_MAX_OVERFLOW`             | 10          | PG 连接池溢出上限                   |
| `DB_POOL_RECYCLE`             | 1800        | PG 连接回收秒数                     |
| `DB_POOL_PRE_PING`            | true        | 取连接前预检活性                    |
| `SUMMARY_THRESHOLD`           | 40          | 触发摘要的消息数阈值                |
| `ROUTER_CONFIDENCE_THRESHOLD` | 0.5         | 路由降级置信度阈值                  |
| `MEMORY_IMPORTANCE_THRESHOLD` | 0.6         | 记忆落库重要性阈值                  |
| `MEMORY_TOP_K`                | 5           | 检索召回条数                        |
| `CONVERSATION_MAX_MESSAGES`   | 20          | 窗口消息数上限                      |
| `CONVERSATION_MAX_CHARS`      | 8000        | 窗口字符上限                        |

## 开发约定

- 禁止在源码硬编码 API Key / 密钥，只从环境变量或 `.env` 读取
- LLM 实例统一来自 `app/core/llm_factory.get_llm()`，禁止各处新建
- DB 访问只能走 `repositories/`，业务层禁止直接操作 ORM
- 不添加代码注释，用命名表达意图
- 不提交 `.env`、`__pycache__/`、`.venv/`、`*.db`
