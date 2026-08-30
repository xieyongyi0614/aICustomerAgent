# AGENTS.md

## 项目概览

「角色对话 Agent」—— 让「亚丝娜」角色成为具备记忆、情感、目标与自主行为的 AI Agent（FastAPI + LangChain + PostgreSQL）。

- 当前开发分支：`feat/v3`
- 开发阶段：V1~V7.8 全部完成（V7.5 Character Evaluation、V7.8 Character Runtime Intelligence 已实现，前端面板按边界跳过；V7.8-014 Metrics 周期快照按设计留白）；后端架构 Refactor 完成
- 上线前待办：按各版本 regression-checklist 执行真实模型人工回归（V4 / V7 / V7.5 / V7.8 已有清单）

## 目录结构

| 路径 | 说明 | 规则位置 |
|---|---|---|
| `apps/backend/` | 后端（Python 3.13 + FastAPI + LangChain） | `apps/backend/AGENTS.md` |
| `apps/frontend/` | 前端调试控制台（React 19 + Vite + Vitest） | `apps/frontend/README.md` |
| `docs/` | 文档（各版本任务注册表、架构设计、回归清单） | — |

## 文档导航

- `docs/roleplay-v7.8/` — V7.8 Character Runtime Intelligence 设计 + 任务注册表（已实现）+ regression-checklist
- `docs/roleplay-v7.5/` — V7.5 Character Evaluation 设计 + 任务注册表（已实现）+ regression-checklist
- `docs/roleplay-v7/` — V7 Autonomous Behavior 设计 + 任务注册表（已实现）+ regression-checklist
- `docs/roleplay-v6.5/` — V6.5 Character Behavior Refinement 设计 + 任务注册表（已实现）
- `docs/roleplay-v6/` — V6 Goal & Intention 设计 + 任务注册表（已实现）
- `docs/roleplay-v5/` — V5 Emotion & Relationship 设计 + 任务注册表（已实现）
- `docs/roleplay-v4/` — V4 Long-term Memory 设计 + 任务注册表（已实现）+ regression-checklist
- `docs/roleplay-v3/` — V3 场景状态与动作连续性设计
- `docs/backend-refactor/` — 后端架构审计与目标架构（application 编排层，已实现）
- `docs/v2/01-task-registry.md` / `docs/v1/01-task-registry.md` — 早期版本（已完结）

## 全局约定

- 禁止在源码硬编码 API Key / 密钥，只从环境变量或 `.env` 读取。
- 不添加代码注释，用命名表达意图。
- 提交风格：`feat:` / `fix:` / `refactor:` / `docs:` + 中文描述。
- 不要提交 `.env`、`__pycache__/`、`.venv/`。
- 只有用户明确要求时才提交 / 推送 / 建 PR。
