# AICustomerServiceAgent Backend

「角色对话 Agent」后端 —— 让「亚丝娜」角色成为具备记忆、情感、目标与自主行为的 AI Agent（FastAPI + LangChain + PostgreSQL）。

## 技术栈

- Python 3.13 + FastAPI + Uvicorn
- LangChain（Chain 编排：路由 / 轮次分析 / 意图 / 场景 / 回答 / 状态更新 / 摘要 / 记忆提取 / 主动消息，统一结构化输出 + 一层降级）
- PostgreSQL 16（SQLAlchemy ORM + Alembic 版本化迁移）+ pydantic-settings
- pytest + pytest-asyncio（FakeLLM 注入，无真实 LLM 调用）

## 目录结构

```
app/
├── api/v1/            # API 表现层（chat / history / state / proactive / llm / debug）
├── application/       # 编排层（chat_pipeline 主管线、post_process 出链步骤、autonomy_engine/worker）
├── services/          # 业务服务（记忆 / 摘要 / 场景 / 情绪状态 / 目标 / 行为 / 习惯 / 自主裁决与执行）
├── repositories/      # 数据访问层（SQLAlchemy，每张表一个仓储）
├── chains/            # LangChain 链（structured 统一结构化输出）
├── core/              # 配置、DB 引擎、LLM 工厂、常量、错误集
├── models/            # Pydantic 领域模型（情绪 / 记忆 / 场景 / 目标 / 意图 / 自主 / 行为策略）
├── prompts/           # Prompt 模板与 PromptBuilder
└── character/asuna/   # 亚丝娜角色资产（人设 / 行为策略 / 模式 / 目标 / 习惯）
```

分层单向依赖，禁止反向引用：

```text
api → application（编排） → services → repositories → core
         chains（LLM 链）┘    engines（纯函数）┘
```

## 快速开始

```bash
# 1. 配置环境变量 + LLM profiles（复制模板，填入真实 API Key）
cp .env.example .env
cp llm_profiles.example.json llm_profiles.json

# 2. 启动本地 PostgreSQL 16（在仓库根目录执行，统一入口为根目录 docker-compose.yml，asuna/asuna/asuna）
docker compose up -d postgres

# 3. 安装依赖并执行数据库迁移
uv sync
uv run alembic upgrade head

# 4. 启动服务
uv run uvicorn app.main:app --reload --port 8020

# 5. 健康检查
curl http://localhost:8020/health
```

`app/main.py` lifespan 启动两个后台循环：记忆回收（memory reclaim）与自主行为 Worker（`AUTONOMY_ENABLED` 门控）。

## 数据库

- 运行库为 PostgreSQL 16，连接串由 `DATABASE_URL` 配置（默认 `postgresql+psycopg://asuna:asuna@localhost:5432/asuna`）。
- Schema 唯一真相是 Alembic 迁移链（`migrations/versions/`，当前链尾 `0050`）；禁止 `create_all` 建表（单元测试内存 SQLite 属豁免）。
- 存量 SQLite 数据可用 `uv run python -m scripts.migrate_sqlite_to_postgres --source sqlite:///./asuna.db` 一次性搬运（幂等，目标表先清后写）。
- 连接池参数（`DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_RECYCLE` / `DB_POOL_PRE_PING`）见配置项表。

## 核心能力

- **流式对话**：NDJSON 三段事件流，会话历史持久化、多轮窗口（长度 / 字符双重预算）
- **角色状态系统（V2）**：情绪 / 行为 / 关系三维状态随对话演化，注入 Prompt
- **场景连续性（V3）**：场景状态、活动 / 动作 pending 机制跨轮延续
- **长期记忆（V4）**：提取 → 策略 → 冲突消解（LCS 同题检测）→ 落库 → 打分召回（词法 / 重要性 / 时效 / 类型加权）→ 注入上下文
- **情绪与关系（V5）**：事件驱动的离散情绪引擎（单轮 Δ 上限 / 惯性 / 按小时衰减）+ 关系四维（intimacy / trust / familiarity / tension）与阶段演化
- **目标与意图（V6）**：持久目标选择（TTL / 深夜豁免）、意图决策与确定性校验
- **行为精修（V6.5）**：策略 / 预算 / 习惯 / 活动四层，动作描写按 ActionBudget 约束并只读观测
- **自主行为（V7）**：闲置触发 → AutonomyPolicy 八步裁决（静音 / 冷却退避 / 集期上限 / 关系门槛等）→ Outbox 状态机 → 主动消息生成发送
- **多模型切换**：消息级 LLM profile 切换（body / header / query 三通道）

## API

### POST /api/v1/chat/message

流式对话端点（NDJSON，`application/x-ndjson`），事件顺序 `turn_meta → delta* → done`：

```json
{"type": "turn_meta", "role_mode": {...}, "analysis": {...}, "behavior": {...}}
{"delta": "你好"}
{"done": true, "session_id": "xxxx", "turn_id": 123}
```

- `turn_meta` 携带本轮编排元数据（模式 / 轮次分析 / 场景 / 意图 / 目标 / 行为指令，字段按可用性缺省）
- 请求体 `{ "content": "...", "session_id": "xxx", "profile_id": "longcat" }`；不带 `session_id` 创建新会话，`content` 为空返回 422
- 模型选择优先级：body `profile_id` > header `X-LLM-Profile` > query 参数；未知 id 在流开始前返回 400
- 响应头：`X-Session-Id`、`X-Session-New`（首次会话 `true`）、`X-LLM-Profile`（回显实际使用 profile）
- LLM 失败 / 空响应在流内返回 `{"detail": "..."}`

### 其他端点

| 端点 | 说明 |
|---|---|
| `GET /api/v1/llm/profiles` | 可用模型列表与默认项 |
| `GET /api/v1/conversations/{conversation_id}/messages` | 会话历史消息（404 = 会话不存在） |
| `GET /api/v1/memories` | 用户长期记忆列表 |
| `GET /api/v1/state` | 角色状态 / 关系 / 情绪史 / 行为快照 |
| `GET /api/v1/proactive/pending` | 待 ack 的主动消息 |
| `POST /api/v1/proactive/{action_id}/ack` | 确认收到主动消息 |
| `GET /api/v1/debug/turns/{turn_id}/trace` | 单轮编排 trace（内存 LRU，过期 404） |

## 测试

```bash
uv run pytest             # 全量 2195 项（16 skipped）
uv run pylint app tests   # 代码检查
```

测试分层于 `tests/unit / integration / e2e / golden`，通过 `tests/conftest.py` 的 FakeLLM（结构化输出按 schema 类名分发）与内存 SQLite（每用例独立建表）运行，不发起真实 LLM 调用；golden prompt 快照用 `UPDATE_GOLDEN=1` 重新生成；`tests/integration/test_db_migration.py` 验证 Alembic 与 ORM 一致，需 `TEST_DATABASE_URL` 指向真实 PostgreSQL（无实例时自动 skip）。

## 配置项（app/core/settings.py）

完整清单见 `app/core/settings.py`（含 memory_* / emotion_* / rel_* / goal_* / mode_* / autonomy_* / energy_* / stage_* 等分组），常用项：

| 配置                          | 默认值      | 说明                                |
| ----------------------------- | ----------- | ----------------------------------- |
| `LLM_PROFILES_JSON`           | -           | 模型 profile 数组内联单行字符串（必填字段：id / label / base_url / model / api_key；可选覆盖：max_tokens、temperature、top_p、frequency_penalty、presence_penalty、extra_body_thinking；可选 `extra_body` 对象原样透传请求体顶层，设置后取代默认 thinking 注入）。与 `LLM_PROFILES_FILE` 同时设置时本项优先 |
| `LLM_PROFILES_FILE`           | -           | profile 数组外置 JSON 文件路径（相对启动目录，如 `llm_profiles.json`，可自由缩进排版）；缺失/读错启动即报 SettingsError |
| `DEFAULT_LLM_PROFILE`         | longcat     | 默认 profile id（必须在数组内）      |
| `ANSWER_MAX_TOKENS`           | 200         | 最终回答链的输出上限；路由/分析/记忆等辅助链不受此限制，使用各 profile 的 `max_tokens`（建议 ≥512） |
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
| `CONTEXT_TOTAL_CHAR_BUDGET`   | 12000       | 单轮注入 Prompt 的上下文总字符预算  |
| `CONVERSATION_MAX_MESSAGES`   | 20          | 窗口消息数上限                      |
| `CONVERSATION_MAX_CHARS`      | 8000        | 窗口字符上限                        |
| `AUTONOMY_ENABLED`            | true        | 自主行为总开关（关闭则 Worker 不启动） |
| `AUTONOMY_INACTIVITY_MINUTES` | 30          | 会话闲置触发阈值                    |
| `AUTONOMY_QUIET_HOURS_*`      | 23:00/08:00 | 主动消息静音时段                    |

## 开发约定

- 禁止在源码硬编码 API Key / 密钥，只从环境变量或 `.env` 读取
- 分层单向依赖：`api → application → services → repositories → core`；编排层只做调度与容错，状态计算在纯函数引擎
- LLM 实例统一来自 `app/core/llm_factory.get_llm()`，结构化输出统一走 `chains/structured.py`，禁止各处新建 / 自由解析
- DB 访问只能走 `repositories/`，业务层禁止直接操作 ORM
- 不添加代码注释，用命名表达意图
- 不提交 `.env`、`__pycache__/`、`.venv/`、`*.db`
