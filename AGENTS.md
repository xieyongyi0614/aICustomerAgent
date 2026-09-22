# AGENTS.md

## 项目概览

「角色对话 Agent」—— 让「亚丝娜」角色成为具备记忆、情感、目标与自主行为的 AI Agent（Python 3.13 + FastAPI + LangChain + PostgreSQL 16）。

- **当前状态基线**：`docs/current-system-architecture-baseline.md` —— **当前系统唯一可信架构基线**，描述**已实现**的真实系统（非规划）。架构类问题先查它；任何架构演进须**先更新该基线再进入开发**。
- 当前分支：`feat/feishu_bot`
- 已实现能力：
  - **V1~V9（对话与角色基座）**：会话与流式对话、角色状态（V2）、场景连续性（V3）、长期记忆（V4）、情绪与关系（V5）、目标与意图（V6）、行为精修（V6.5）、自主行为（V7）、角色评估（V7.5）、运行时智能（V7.8）、世界状态（V8）、关系演化（V8.5）、行动能力（V9）。
  - **V2.0.0**：Memory V2 / Reflection / Development / Life Loop / Action Engine / Autonomy Advanced（六 Phase）。
  - **V2.1.0**：Agent Runtime（Run 台账 / Profile 注册表 / Trigger Router / LLM Gateway）、Character State、Goal Stack、Decision Pipeline、Evolution、Agent Evaluation。
  - **V2.2.0** Character（CHAR-001~007）、**V2.3.0** World Simulation（WS-001~019）、**V2.4.0** Tool System（TOOL-001~012）、**V2.5.0** Planning System（PLAN-001~012）、**V2.6.0 / V2.6.1** Action Execution（TASK-001~009）+ Reflection（REF-001~007）。
  - **横切**：Channel Adapter 接入（Web + 飞书机器人真实链路验证）、后端架构重构（新增 `application/` 编排层）、Feature Flag 清理、`vXX_` 版本变量清理（2026-09-19 收官）。
- **迁移链尾：`0052`**（Schema 唯一真相 = Alembic 迁移链）。
- 上线前待办：按各版本 regression-checklist 执行真实模型人工回归（V4 / V7 / V7.5 / V7.8 / V8 / V2.0.0 六 phase / V2.1.0~V2.6.1 均已有清单）。已关闭的留白：V7.8-014 Metrics 周期快照由 V2.1.0 AGENT-006（`agent_metric_snapshots`）补齐。

## 目录结构

| 路径 | 说明 | 规则位置 |
|---|---|---|
| `apps/backend/` | 后端（Python 3.13 + FastAPI + LangChain + PostgreSQL 16） | `apps/backend/AGENTS.md` |
| `apps/frontend/` | 前端调试控制台 Debug Console（React 19 + TS + Vite + TanStack Query + Zustand + Tailwind 4） | `apps/frontend/README.md` |
| `docs/` | 文档：当前架构基线、各版本任务注册表/架构设计/回归清单、横切重构台账、通道集成文档 | — |

## 文档导航

**当前基线（最优先）**

- `docs/current-system-architecture-baseline.md` — 当前系统唯一可信架构基线（分层/模块/数据/配置/扩展点/技术债/ADR/演进方向）

**当前版本（V2.x）**

- `docs/version/v2.6.1/` — V2.6.1 Reflection（REF-001~007）
- `docs/version/v2.6.0/` — V2.6.0 Action Execution（TASK-001~009）+ architecture / acceptance-report / audit-report
- `docs/version/v2.5.0/planning-system/` — V2.5.0 Planning System（PLAN-001~012）
- `docs/version/v2.4.0/tool-system/` — V2.4.0 Tool System（TOOL-001~012）
- `docs/version/v2.3.0/` — V2.3.0 World Simulation（WS-001~019）
- `docs/version/v2.2.0/` — V2.2.0 Character（CHAR-001~007）
- `docs/version/v2.1.0/` — V2.1.0 Agent Evolution / Agent Runtime（AGENT-001~007）+ code-review
- `docs/version/v2.0.1/` — V2.0.1 Autonomy（AUTO-001~007）
- `docs/version/v2.0.0/` — V2.0.0 六 Phase 深化 + architecture/ + phases/ + acceptance/

**历史版本（V1.x）**

- `docs/version/v1.0.0/v9/` — V9 Action Capability System（含 regression-checklist）
- `docs/version/v1.0.0/v8/` — V8 World State System（含 V8-015 World Consistency 评估规则）
- `docs/version/v1.0.0/v8.5/` — V8.5 Relationship Evolution System（V5 关系域深化，与 V8 相互独立；V2.0.0 Phase4 落地）
- `docs/version/v1.0.0/v7.8/` · `v7.5/` · `v7/` · `v6.5/` · `v6/` · `v5/` · `v4/` · `v3/` — 各版本设计 + 任务注册表（已实现）
- `docs/version/v1.0.0/backend-refactor/` — 后端架构审计与目标架构（`target-architecture.md` 是**分层边界**的权威描述）
- `docs/version/v1.0.0/v2/01-task-registry.md` · `v1/01-task-registry.md` — 早期版本（已完结）

**横切与集成**

- `docs/integrations/feishu/` — 飞书通道：`architecture.md`（本域唯一架构依据）+ `tasks.md`（FEISHU-001~007）+ `task-details/` + `acceptance-report-v1.0.md` + `review-v1.1.md`
- `docs/refactor/` — 横切重构：`flag-removal-audit.md`（vXX_ 开关体系删除成本审查 + 批次台账）、`flag-rename-map.md`（设置字段「旧名 → 新名」对照表）
- `docs/TESTING.md` — 测试规范（marker、执行级别、AI Coding 测试规则）

## 全局约定

- 禁止在源码硬编码 API Key / 密钥，只从环境变量或 `.env` 读取。
- 不添加代码注释，用命名表达意图。
- 提交风格：`feat:` / `fix:` / `refactor:` / `docs:` + 简短中文描述。单行、≤ 30 字，只概括核心变更；不罗列修改文件清单、不写实现细节与测试结果。
- 不要提交 `.env`、`__pycache__/`、`.venv/`。
- 设置字段与 env 键**不带版本号前缀**（`vXX_` 开关体系删除已收官，2026-09-19，台账见 `docs/refactor/flag-removal-audit.md`）：新增设置项按领域命名（如 `plan_max_steps` / `world_prompt_char_budget`），勿再引入版本前缀；环境变量名 = 字段名大写（无 alias 层），改名必须同批同步部署侧 `.env`。
- 版本门控体系已整体删除（`core/settings/enablement.py` 不再存在）；**残留的少数布尔开关是策略位 / 裁决位 / 调试位，不是版本门控**，新增开关请按领域语义命名。
- 只有用户明确要求时才提交 / 推送 / 建 PR。
