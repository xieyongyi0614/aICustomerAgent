# AICustomerServiceAgent

「角色对话 Agent」—— 让「亚丝娜」角色成为具备记忆、情感、目标与自主行为的 AI Agent。后端基于 FastAPI + LangChain + PostgreSQL 提供流式对话，前端为 React 调试控制台（Debug Console）。

能力覆盖：角色身份 / 场景状态与动作连续性 / 长期记忆 / 情绪与关系 / 目标与意图 / 行为策略与习惯 / 自主行为（主动消息）。

## 技术栈

| 端 | 技术 |
|---|---|
| 后端（`apps/backend/`） | Python 3.13 + FastAPI + LangChain + PostgreSQL 16（SQLAlchemy + Alembic），uv 管理依赖 |
| 前端（`apps/frontend/`） | React 19 + TypeScript + Vite + TanStack Query + Zustand + Tailwind 4，vitest 测试 |
| 部署 | Docker 多阶段构建（根目录 `Dockerfile`）+ docker compose（根目录唯一入口） |

## 目录结构

```
├── apps/
│   ├── backend/           # FastAPI 后端（详见 apps/backend/README.md）
│   │   ├── app/           #   api / application / services / repositories / chains / core / prompts / character
│   │   ├── migrations/    #   Alembic 迁移链（0001 ~ 0011）
│   │   └── tests/         #   pytest 分层（unit / integration / e2e / golden；FakeLLM 注入）
│   └── frontend/          # React 调试控制台（详见 apps/frontend/README.md）
│       └── src/           #   api / app / components / features / hooks / stores / mocks
├── docs/                  # 文档（按版本归档，当前 V1.0.0 封版）
│   └── version/
│       └── v1.0.0/        # V1.0.0 全部文档
│           ├── v7.5/      #   V7.5 Character Evaluation 设计（当前任务入口）
│           ├── v*/        #   V1~V9 各版本文档
│           ├── frontend/  #   前端调试控制台设计
│           └── backend-refactor/  # 后端架构重构设计
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
npm run dev                 # http://localhost:2000，/api 代理到 :8000
```

> 环境变量说明见 `apps/backend/README.md` 的配置项表；模型通过 `LLM_PROFILES_JSON`（OpenAI 兼容服务商数组）配置。

## 测试

```bash
# 后端（apps/backend/ 下；全量约 858 项，无本地 PG 实例时迁移一致性用例自动 skip）
uv run pytest
uv run pylint app tests

# 前端（apps/frontend/ 下）
npm run test        # vitest
npm run typecheck   # tsc -b
npm run lint        # eslint
```

## 核心能力

- **流式对话**：NDJSON 流式返回（turn_meta → delta* → done），支持会话续接（`session_id`）
- **角色状态系统（V2）**：情绪 / 行为 / 关系三维状态随对话演化，注入 Prompt
- **场景连续性（V3）**：场景状态、活动 / 动作 pending 机制跨轮延续
- **长期记忆（V4）**：自动提取用户事实与偏好，冲突消解后落库，检索召回注入上下文
- **情绪与关系（V5）**：离散情绪引擎（事件驱动 + 衰减）与关系四维（intimacy/trust/familiarity/tension）演化
- **目标与意图（V6）**：持久目标选择、意图决策与校验，驱动回复策略
- **行为精修（V6.5）**：行为策略 / 预算 / 习惯 / 活动分层，动作描写受预算约束
- **自主行为（V7）**：闲置触发 → 八步裁决 → 主动消息生成与发送（Outbox + 状态机，静音时段 / 冷却退避 / 防轰炸闸）
- **长期记忆召回**：对话中自动提取用户偏好落库并召回（V1 起持续可用）
- **多模型切换**：顶栏选择器按消息级切换 LLM profile（body `profile_id` > header `X-LLM-Profile` > query 参数）

## 主要 API（前缀 `/api/v1`）

| 端点 | 说明 |
|---|---|
| `POST /chat/message` | 流式对话（NDJSON：turn_meta → delta* → done），响应头回显会话与实际使用的 profile |
| `GET /conversations/{conversation_id}/messages` | 查询指定会话的历史消息（前端刷新回填数据源，404 表示会话不存在） |
| `GET /memories` | 查询用户长期记忆列表 |
| `GET /state` | 角色当前状态查询（状态 / 关系 / 情绪史 / 行为快照） |
| `GET /proactive/pending` | 查询待 ack 的主动消息 |
| `POST /proactive/{action_id}/ack` | 确认收到主动消息 |
| `GET /llm/profiles` | 可用模型 profile 列表与默认项 |
| `GET /debug/turns/{turn_id}/trace` | 单轮编排 trace（调试用） |

完整请求 / 响应契约见 `apps/backend/README.md` 与 `docs/version/v1.0.0/frontend/deploy.md`。

## 文档导航

- `docs/version/v1.0.0/v7.5/tasks.md` — V7.5 任务注册表（当前任务入口，待实现）
- `docs/version/v1.0.0/v7/` ~ `docs/version/v1.0.0/v3/` — 各版本设计文档与任务注册表（V3~V7 已实现）
- `docs/version/v1.0.0/backend-refactor/target-architecture.md` — 后端目标架构与分层边界
- `docs/version/v1.0.0/frontend/deploy.md` — 前端部署指南（三种方案 + 冒烟清单）
- `AGENTS.md` / `apps/backend/AGENTS.md` — 仓库与后端开发约定（面向 Coding Agent）

## 开发约定（摘自 AGENTS.md）

- 禁止在源码硬编码 API Key / 密钥，只从环境变量或 `.env` 读取；不提交 `.env`
- 分层单向依赖：`api → application → services → repositories → core`；LLM 统一来自 `llm_factory.get_llm()`
- DB 访问只走 `repositories/`；schema 变更只走 Alembic revision
- 不添加代码注释，用命名表达意图；提交风格：`feat:` / `fix:` / `refactor:` / `docs:` + 中文描述
