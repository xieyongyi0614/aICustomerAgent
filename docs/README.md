# docs 文档导航

## 首读

| 文档 | 说明 |
|---|---|
| `current-system-architecture-baseline.md` | **当前系统唯一可信架构基线**（分层 / 模块 / 数据 / 配置 / 扩展点 / 技术债 / ADR / 演进方向）。架构类问题先查它；架构演进须先更新基线再进入开发 |

## 版本目录（`version/`）

| 目录 | 主题 | 状态 |
|---|---|---|
| `v6.0.0/` | Agent Evolution（`MEV-` 记忆演进 / `PLN-` 计划澄清 / `SAG-` 子 Agent 未排期） | 进行中（Task Detail 已就位） |
| `v5.0.0/` | 朝夕 App 客户端（Flutter）：需求分析 / 任务注册表 / 客户端架构 / 免商店更新 / 合规 | 已实现；同目录含 V5.1 增量清单与人工回归清单 |
| `v4.0.0/` | Personal Life Agent Foundation（用户实体 + 账本域） | 已实现 |
| `v3.0.0/` | Agent Runtime Core（RT-001~020） | `acceptance-report` 为 CONDITIONAL — NOT RELEASED |
| `v2.6.1/` · `v2.6.0/` | Reflection（REF-001~007）· Action Execution（TASK-001~009） | 已实现 |
| `v2.5.0/planning-system/` | Planning System（PLAN-001~012） | 已实现 |
| `v2.4.0/tool-system/` | Tool System（TOOL-001~012） | 已实现 |
| `v2.3.0/` | World Simulation（WS-001~019） | 已实现 |
| `v2.2.0/` | Character（CHAR-001~007） | 已实现 |
| `v2.1.0/` | Agent Runtime / Agent Evolution（AGENT-001~007） | 已实现 |
| `v2.0.1/` | Autonomy（AUTO-001~007） | 已实现 |
| `v2.0.0/` | 六 Phase 深化（Memory V2 / Reflection / Development / Life Loop / Action Engine / Autonomy Advanced） | 已实现 |
| `v1.0.0/` | V1~V9 对话与角色基座（`v1/` ~ `v9/` 各有设计、任务注册表、回归清单）+ `frontend/` 调试控制台 | 已实现 |

每个版本目录通常包含：`README.md`（概览）、`architecture.md`（架构依据）、`tasks.md`（任务注册表）、`tasks/`（Task Detail 明细）、`regression-checklist.md`（真实模型人工回归清单）。

## 横切与专题

| 路径 | 说明 |
|---|---|
| `integrations/feishu/` | 飞书通道：`architecture.md` + `tasks.md`（FEISHU-001~007）+ 验收报告与复核 |
| `integrations/wechat/` | 微信通道接入文档 |
| `architecture-visualization/current-state/` | 当前态架构可视化图谱（`.dot` / `.dsl` / 说明） |
| `refactor/` | 后端架构评审、重构任务清单、交互式 Plan Mode 评估、记忆迁移与版本命名审计 |
| `TESTING.md` | 测试规范（marker、执行级别、AI Coding 测试规则） |
| `prompt/` | 任务注册表生成 / 执行用的 prompt 模板 |
| `chat-message-flow*` · `llm-call-flow.md` | 对话与 LLM 调用全链路分析 |
| `design-alignment-report.md` | 客户端与设计系统对齐报告 |
| `agent-evolution-plan-2026-10.md` | V6.0.0 上游演进方案（记忆 / 交互式澄清 / subAgent 可行性） |
| `backend-test-audit-2026-10-09.md` | 后端测试审计报告 |
| `household-inventory-review.md` | Household Inventory 对话审查（叙事与世界状态脱节分析） |

## 归档（`_archive/`）

个人学习笔记与过程讨论，不再维护：`learningPath.md`（LangChain 学习路线）、`test.md`（早期架构讨论）。
