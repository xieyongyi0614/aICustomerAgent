# AGENTS.md

## 项目概览

「角色对话 Agent」—— 让「亚丝娜」角色成为具备记忆、情感、目标与自主行为的 AI Agent（FastAPI + LangChain + PostgreSQL）。

- 当前开发分支：`feat/v2.0.0`
- 开发阶段：V1~V9 全部完成（V7.5 Character Evaluation、V7.8 Character Runtime Intelligence、V8 World State System、V8.5 Relationship Evolution System、V9 Action Capability System 已实现）；后端架构 Refactor 完成；V2.0.0（Memory V2 / Reflection / Development / Life Loop / Action Engine / Autonomy Advanced）已实现；V2.1.0（Agent Runtime / Character State / Goal Stack / Decision Pipeline / Evolution / Agent Evaluation）已实现（迁移链至 0043）
- 上线前待办：按各版本 regression-checklist 执行真实模型人工回归（V4 / V7 / V7.5 / V7.8 / V8 / V2.1.0 已有清单）；V7.8-014 Metrics 周期快照留白已由 V2.1.0 AGENT-006（`agent_metric_snapshots`）关闭

## 目录结构

| 路径 | 说明 | 规则位置 |
|---|---|---|
| `apps/backend/` | 后端（Python 3.13 + FastAPI + LangChain） | `apps/backend/AGENTS.md` |
| `apps/frontend/` | 前端调试控制台（React 19 + Vite + Vitest） | `apps/frontend/README.md` |
| `docs/` | 文档（各版本任务注册表、架构设计、回归清单） | — |

## 文档导航

- `docs/version/v1.0.0/v9/` — V9 Action Capability System 设计 + 任务注册表（已实现）+ regression-checklist
- `docs/version/v1.0.0/v8/` — V8 World State System 设计 + 任务注册表（已实现，含 V8-015 World Consistency 评估规则）+ regression-checklist
- `docs/version/v1.0.0/v8.5/` — V8.5 Relationship Evolution System 设计（13 篇，已实现；V5 关系域深化，与 V8 相互独立；V2.0.0 Phase4 落地）
- `docs/version/v1.0.0/v7.8/` — V7.8 Character Runtime Intelligence 设计 + 任务注册表（已实现）+ regression-checklist
- `docs/version/v1.0.0/v7.5/` — V7.5 Character Evaluation 设计 + 任务注册表（已实现）+ regression-checklist
- `docs/version/v1.0.0/v7/` — V7 Autonomous Behavior 设计 + 任务注册表（已实现）+ regression-checklist
- `docs/version/v1.0.0/v6.5/` — V6.5 Character Behavior Refinement 设计 + 任务注册表（已实现）
- `docs/version/v1.0.0/v6/` — V6 Goal & Intention 设计 + 任务注册表（已实现）
- `docs/version/v1.0.0/v5/` — V5 Emotion & Relationship 设计 + 任务注册表（已实现）
- `docs/version/v1.0.0/v4/` — V4 Long-term Memory 设计 + 任务注册表（已实现）+ regression-checklist
- `docs/version/v1.0.0/v3/` — V3 场景状态与动作连续性设计
- `docs/version/v1.0.0/backend-refactor/` — 后端架构审计与目标架构（application 编排层，已实现）
- `docs/version/v1.0.0/v2/01-task-registry.md` / `docs/version/v1.0.0/v1/01-task-registry.md` — 早期版本（已完结）
- `docs/version/v2.1.0/` — V2.1.0 Agent Evolution 架构 + 任务注册表（AGENT-001~007 已实现）+ Task Detail + regression-checklist + code-review

## 全局约定

- 禁止在源码硬编码 API Key / 密钥，只从环境变量或 `.env` 读取。
- 不添加代码注释，用命名表达意图。
- 提交风格：`feat:` / `fix:` / `refactor:` / `docs:` + 简短中文描述。单行、≤ 30 字，只概括核心变更；不罗列修改文件清单、不写实现细节与测试结果。
- 不要提交 `.env`、`__pycache__/`、`.venv/`。
- 只有用户明确要求时才提交 / 推送 / 建 PR。
