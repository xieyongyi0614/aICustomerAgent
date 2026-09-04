# docs 文档导航

项目文档按版本归档。当前处于 **V1.0.0 封版**，所有版本文档、前端文档、后端架构重构文档统一收在 `version/v1.0.0/` 下。

## 版本 v1.0.0（`version/v1.0.0/`）

| 目录 | 内容 |
|---|---|
| `v1/` ~ `v9/` | 各能力版本设计 / 任务注册表 / 回归清单 |
| `frontend/` | 前端调试控制台架构 / 任务 / 部署 |
| `backend-refactor/` | 后端架构审计与目标架构（REF-001~013） |

### 版本文档（`version/v1.0.0/v*/`）

| 目录 | 版本 | 能力 |
|---|---|---|
| `v1/` | V1 | 基础版：三层架构 / 记忆 / 对话历史 |
| `v2/` | V2 | 角色状态系统：情绪 / 行为 / 关系 |
| `v3/` | V3 | 场景状态与动作连续性 |
| `v4/` | V4 | 长期记忆系统 |
| `v5/` | V5 | 情绪与关系动态 |
| `v6/` | V6 | 目标与意图 |
| `v6.5/` | V6.5 | 行为精化（Behavior Refinement） |
| `v7/` | V7 | 自主行为（Autonomous Behavior） |
| `v7.5/` | V7.5 | 角色一致性评估（只读旁路） |
| `v7.8/` | V7.8 | 运行时智能（只读旁路） |
| `v8/` | V8 | 世界状态系统 |
| `v8.5/` | V8.5 | 关系演化系统 |
| `v9/` | V9 | 行动能力系统 |

每个版本目录内含 `README.md`（概览）、`architecture.md`（架构）、`tasks.md`（任务注册表）、各能力子文档、`testing.md`（测试计划）、`regression-checklist.md`（真实模型人工回归清单）。

## 其他文档（`docs/`）

| 路径 | 说明 |
|---|---|
| `prompt/` | AI 辅助开发用的任务生成 / 执行 prompt 模板 |
| `TESTING.md` | 后端测试规范（marker、执行级别） |
| `chat-message-link-analysis.md` | `POST /chat/message` 全链路技术分析 |
| `PR-feat-v3-to-main.md` / `-lite.md` | feat/v3 → main 合并 PR 描述 |

## 归档（`docs/_archive/`）

个人学习笔记与过程讨论，不再维护：

- `learningPath.md` — LangChain 学习路线
- `test.md` — 早期架构讨论笔记
