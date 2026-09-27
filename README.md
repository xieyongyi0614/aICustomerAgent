# AICustomerServiceAgent

「角色对话 Agent」—— 让「亚丝娜」角色成为具备记忆、情感、目标与自主行为的 AI Agent。后端基于 FastAPI + LangChain + PostgreSQL 提供流式对话，前端为 React 调试控制台（Debug Console）。

能力覆盖：角色身份 / 场景状态与动作连续性 / 长期记忆 / 情绪与关系 / 目标与意图 / 行为策略与习惯 / 自主行为（主动消息）。

## 技术栈

| 端 | 技术 |
|---|---|
| 后端（`apps/backend/`） | Python 3.13 + FastAPI + LangChain + PostgreSQL 16（SQLAlchemy + Alembic），uv 管理依赖 |
| 前端（`apps/frontend/`） | React 19 + TypeScript + Vite + TanStack Query + Zustand + Tailwind 4，vitest 测试 |
| 移动端（`apps/mobile/`） | Flutter ≥ 3.44 + Riverpod 3 + GoRouter + Dio + Freezed + Drift(SQLite)，朝夕 App（V5.0.0，产品级客户端） |
| 部署 | Docker 多阶段构建（根目录 `Dockerfile`）+ docker compose（根目录唯一入口） |

## 目录结构

```
├── apps/
│   ├── backend/           # FastAPI 后端（详见 apps/backend/README.md）
│   │   ├── app/           #   api / application / services / repositories / chains / core / prompts / character
│   │   ├── migrations/    #   Alembic 迁移链（0001 ~ 0011）
│   │   └── tests/         #   pytest 分层（unit / integration / e2e / golden；FakeLLM 注入）
│   ├── frontend/          # React 调试控制台（详见 apps/frontend/README.md）
│   │   └── src/           #   api / app / components / features / hooks / stores / mocks
│   └── mobile/            # 朝夕 App Flutter 客户端（详见 apps/mobile/README.md）
│       └── lib/           #   app / core / design_system / features（按域垂直切分）
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
# 1. 复制 .env 并填入可用 API Key（容器方式推荐内联：LLM_PROFILES_JSON 写成单行 JSON，compose 会注入为环境变量）
cp apps/backend/.env.example apps/backend/.env

# 2. 构建并启动（自动执行 alembic 迁移 + 托管前端产物）
docker compose up -d --build

# 3. 浏览器访问 http://localhost:8020
```

### 方式二：本地开发

```bash
# 1. 启动 PostgreSQL 16 + Redis（统一入口为根目录 compose；Redis 供邮箱验证码登录）
docker compose up -d postgres redis

# 2. 后端（apps/backend/ 下）：配置 LLM profiles + 安装依赖 + 迁移 + 启动
cd apps/backend
cp .env.example .env                            # 环境变量模板
cp llm_profiles.example.json llm_profiles.json  # profiles 模板（api_key 为空串），填入真实 Key 即可自由排版
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8020

# 3. 前端（apps/frontend/ 下）：启动开发服务器
cd apps/frontend
npm install
npm run dev                 # http://localhost:2000，/api 代理到 :8020（VITE_PROXY_TARGET 可配置）

# 4. 移动端（apps/mobile/ 下）：朝夕 App，模拟器/登录流程见 apps/mobile/README.md
cd apps/mobile
flutter pub get
adb reverse tcp:8020 tcp:8020                               # 模拟器端口隧道（重启模拟器后重跑）
flutter run --dart-define-from-file=dart_defines/dev.json --flavor dev -d emulator-5554   # 或 VS Code 打开仓库根，F5 选「朝夕 App」启动配置
```

> 移动端要求 Flutter ≥ 3.44.0（Dart ≥ 3.13.4）；`API_BASE_URL` 未注入时启动即 fail-fast，地址改 `apps/mobile/dart_defines/dev.json` 一处即可。登录走**邮箱验证码**（未注册邮箱自动建号）：后端 `.env` 需配置 `REDIS_URL` + `EMAIL_SMTP_*`（163 用授权码）+ `AUTH_TOKEN_SECRET`，缺一登录端点 503；配对码链路已退役。

> 环境变量说明见 `apps/backend/README.md` 的配置项表。LLM profile 两种配置方式（`LLM_PROFILES_JSON` 优先级更高，同时配置时忽略文件）：本地开发用 `LLM_PROFILES_FILE` 指向外置 JSON 文件（如 `llm_profiles.json`，可排版）；容器 / 内联场景把 `LLM_PROFILES_JSON` 写成单行数组。

## 测试

```bash
# 后端（apps/backend/ 下；全量 7165 项，无本地 PG 实例时迁移一致性用例自动 skip）
uv run pytest
uv run pylint app tests

# 前端（apps/frontend/ 下）
npm run test        # vitest
npm run typecheck   # tsc -b
npm run lint        # eslint

# 移动端（apps/mobile/ 下；单元 + widget + golden 视觉回归）
flutter test
flutter test integration_test   # 冒烟
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
