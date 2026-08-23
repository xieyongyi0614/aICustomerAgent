# AGENTS.md

## 项目概览

「角色对话 Agent」—— 让「亚丝娜」角色成为具备记忆能力的 AI Agent（FastAPI + LangChain + SQLite）。

- 当前开发分支：`feat/v2`
- 开发阶段：V2（角色状态系统），任务见 `docs/v2/01-task-registry.md`

## 目录结构

| 路径 | 说明 | 规则位置 |
|---|---|---|
| `apps/backend/` | 后端（Python 3.13 + FastAPI + LangChain） | `apps/backend/AGENTS.md` |
| `docs/` | 文档（任务注册表、架构设计） | — |

## 文档导航

- `docs/v2/01-task-registry.md` — V2 任务注册表（当前唯一入口）
- `docs/v2/v2-architecture.md` — V2 角色状态系统设计
- `docs/v1/01-task-registry.md` — V1 任务注册表（已完结）
- `docs/v1/v1-architecture.md` — V1 三层架构设计

## 全局约定

- 禁止在源码硬编码 API Key / 密钥，只从环境变量或 `.env` 读取。
- 不添加代码注释，用命名表达意图。
- 提交风格：`feat:` / `fix:` / `refactor:` + 中文描述。
- 不要提交 `.env`、`__pycache__/`、`.venv/`。
- 只有用户明确要求时才提交 / 推送 / 建 PR。