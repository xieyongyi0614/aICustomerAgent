# AICustomerServiceAgent

「角色对话 Agent」—— 让「亚丝娜」角色成为具备记忆能力的 AI Agent。后端基于 FastAPI + LangChain + PostgreSQL 提供流式对话，前端为 React 调试控制台（Debug Console），支持长期记忆、对话摘要、角色状态演化与多模型切换。

## 技术栈

| 端 | 技术 |
|---|---|
| 后端（`apps/backend/`） | Python 3.13 + FastAPI + LangChain + PostgreSQL 16（SQLAlchemy + Alembic），uv 管理依赖 |
| 前端（`apps/frontend/`） | React 19 + TypeScript + Vite + TanStack Query + Zustand，vitest 测试 |
| 部署 | Docker 多阶段构建（根目录 `Dockerfile`）+ docker compose（根目录唯一入口） |

## 目录结构

```
├── apps/
│   ├── backend/           # FastAPI 后端（详见 apps/backend/README.md）
│   │   ├── app/           #   api / services / repositories / chains / core / prompts / character
│   │   ├── migrations/    #   Alembic 迁移链
│   │   └── tests/         #   pytest（FakeLLM 注入，无真实 LLM 调用）
│   └── frontend/          # React 调试控制台
│       └── src/           #   api / components / hooks / stores / mocks
├── docs/                  # 文档（任务注册表、架构设计、部署指南）
│   └── v2/                # 当前开发阶段的唯一任务入口与设计文档
├── docker-compose.yml     # Docker 唯一入口（postgres 开发库 + console 完整栈）
└── Dockerfile             # 多阶段构建：node 构建前端 → python 托管后端 + dist
```

## 快速开始

### 方式一：Docker 一键起完整栈（推荐体验）

```bash
# 1. 配置环境变量（在 LLM_PROFILES_JSON 中填入可用的 API Key）
cp apps/backend/.env.example apps/backend/.env

# 2. 构建并启动（自动执行 alembic 迁移 + 托管前端产物）
docker compose up -d --build

# 3. 浏览器访问 http://localhost:8020
```

### 方式二：本地开发

```bash
# 1. 只启动 PostgreSQL 16 数据库（统一入口为根目录 compose）
docker compose up -d postgres

# 2. 后端（apps/backend/ 下）：安装依赖 + 迁移 + 启动
cd apps/backend
cp .env.example .env        # 并填入 LLM_PROFILES_JSON 的 API Key
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# 3. 前端（apps/frontend/ 下）：启动开发服务器
cd apps/frontend
npm install
npm run dev
```

> 环境变量说明见 `apps/backend/README.md` 的配置项表；模型通过 `LLM_PROFILES_JSON`（OpenAI 兼容服务商数组）配置。

## 测试

```bash
# 后端（apps/backend/ 下；无本地 PG 实例时 PG 集成用例自动 skip）
uv run pytest
uv run pylint app tests

# 前端（apps/frontend/ 下）
npm run test        # vitest
npm run typecheck   # tsc -b
npm run lint        # eslint
```

## 核心能力

- **流式对话**：NDJSON 流式返回，支持会话续接（`session_id`）
- **会话历史持久化**：每轮消息写入 PostgreSQL，刷新页面后前端按会话自动回填历史记录，跨会话/重启可续聊
- **多模型切换**：顶栏选择器按消息级切换 LLM profile（body `profile_id` > header `X-LLM-Profile` > query 参数）
- **长期记忆**：对话中自动提取用户偏好落库并召回
- **对话摘要**：消息数达阈值后滚动摘要，替换窗口外上下文
- **角色状态系统（V2）**：情绪 / 行为 / 关系三维状态随对话演化，注入 Prompt

## 主要 API（前缀 `/api/v1`）

| 端点 | 说明 |
|---|---|
| `POST /chat/message` | 流式对话（NDJSON），响应头回显会话与实际使用的 profile |
| `GET /conversations/{conversation_id}/messages` | 查询指定会话的历史消息（前端刷新回填数据源，404 表示会话不存在） |
| `GET /memories` | 查询用户长期记忆列表 |
| `GET /llm/profiles` | 可用模型 profile 列表与默认项 |
| `GET /state` | 角色当前状态查询 |
| `GET /debug/turns/{turn_id}/trace` | 单轮编排 trace（调试用） |

完整请求 / 响应契约见 `apps/backend/README.md` 与 `docs/frontend/deploy.md`。

## 文档导航

- `docs/v2/01-task-registry.md` — V2 任务注册表（当前唯一任务入口）
- `docs/v2/v2-architecture.md` — V2 角色状态系统架构设计
- `docs/v1/01-task-registry.md` / `docs/v1/v1-architecture.md` — V1 历史
- `docs/frontend/deploy.md` — 前端部署指南（三种方案 + 冒烟清单）
- `AGENTS.md` — 仓库开发约定（面向 Coding Agent）

## 开发约定（摘自 AGENTS.md）

- 禁止在源码硬编码 API Key / 密钥，只从环境变量或 `.env` 读取；不提交 `.env`
- 后端三层单向依赖：`api → services → repositories → core`；LLM 统一来自 `llm_factory.get_llm()`
- DB 访问只走 `repositories/`；schema 变更只走 Alembic revision
- 不添加代码注释，用命名表达意图；提交风格：`feat:` / `fix:` / `refactor:` + 中文描述
