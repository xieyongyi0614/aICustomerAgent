# AGENTS.md

## 项目概览

「角色对话 Agent」—— 让「亚丝娜」角色成为具备记忆能力的 AI Agent（FastAPI + LangChain + PostgreSQL）。

- 当前开发分支：`feat/v3`
- 开发阶段：V4（Long-term Memory）已完成并验收，任务见 `docs/roleplay-v4/tasks.md`；V5 规划见 `docs/roleplay-v5/`
- 上线前待办：按 `docs/roleplay-v4/regression-checklist.md` 执行真实模型人工回归

## 目录结构

| 路径 | 说明 | 规则位置 |
|---|---|---|
| `apps/backend/` | 后端（Python 3.13 + FastAPI + LangChain） | `apps/backend/AGENTS.md` |
| `apps/frontend/` | 前端（React + Vite + Vitest） | — |
| `docs/` | 文档（任务注册表、架构设计） | — |

## 文档导航

- `docs/roleplay-v4/tasks.md` — V4 任务注册表（V4-001~012 已全部完成）
- `docs/roleplay-v4/architecture.md` — V4 长期记忆架构设计（管线：Extractor → Policy → Conflict → Repository → Retrieval → Context）
- `docs/roleplay-v4/regression-checklist.md` — V4 真实模型人工回归清单（待执行）
- `docs/roleplay-v5/` — V5 规划文档
- `docs/roleplay-v3/` — V3 场景状态与动作连续性设计
- `docs/v2/01-task-registry.md` — V2 任务注册表（已完结）
- `docs/v1/01-task-registry.md` — V1 任务注册表（已完结）

## 全局约定

- 禁止在源码硬编码 API Key / 密钥，只从环境变量或 `.env` 读取。
- 不添加代码注释，用命名表达意图。
- 提交风格：`feat:` / `fix:` / `refactor:` + 中文描述。
- 不要提交 `.env`、`__pycache__/`、`.venv/`。
- 只有用户明确要求时才提交 / 推送 / 建 PR。