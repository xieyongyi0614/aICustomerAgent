# 当前态架构可视化

> 快照：2026-10-23 · HEAD `e07669d7` · 分支 `feat/design-car-album`
> 用途：让新成员、架构评审者和 AI Agent 在不读完全部代码的情况下，快速建立对系统边界、运行链路与数据归属的正确心智模型。
> 约束：本目录只描述**当前态**。目标态、规划项、影子实现必须显式标注，不得混入主路径。

## 产物清单

| 文件 | 回答的问题 | 格式 / 查看方式 |
|---|---|---|
| `system-model.structurizr.dsl` | 系统由谁使用、由哪些容器组成、后端组件如何分层 | Structurizr DSL；用 Qoder 的 Structurizr DSL viewer 打开 |
| `backend-module-dependencies.dot` | 后端分层的允许依赖方向与禁止反向依赖 | Graphviz DOT；用 Qoder 的 DOT viewer 打开 |
| `foreground-chat-flow.dot` | 一次用户消息如何从通道走到回答、落库与后台后处理 | Graphviz DOT |
| `autonomous-tick-flow.dot` | 后台 life_loop 如何自治、决策与维护 | Graphviz DOT |
| `data-domains.dot` | 57 张表按什么域归属，谁是 Source of Truth | Graphviz DOT |
| `capability-map.dot` | 用业务语言看系统提供什么价值 | Graphviz DOT |
| `architecture-understanding.md` | 完整叙述：边界、容器、Profile、链路、规则、证据强度 | Markdown |
| `evidence.md` | 每个重要结论的证据、置信度、未知项与验证动作 | Markdown |

## 建议阅读顺序

1. `architecture-understanding.md` §1–§4（先建立业务与容器心智模型）。
2. `system-model.structurizr.dsl`（SystemContext → Containers → BackendComponents）。
3. `foreground-chat-flow.dot` + `autonomous-tick-flow.dot`（两条最重要的运行链路）。
4. `data-domains.dot`（数据归属与 Source of Truth）。
5. `backend-module-dependencies.dot`（分层约束）。
6. `capability-map.dot`（回到业务价值）。
7. `evidence.md`（任何结论的出处与待验证项）。

## 当前态 / 非当前态的边界

- **当前态**：C4 容器与组件、三条 Run Profile、前台 21 步、后台 tick、57 张表、通道与外部系统。
- **影子 / 测试实现**：六段认知循环（observe/reason/plan/act/reflect/update）默认不进入生产路径；开关可切换，但不属于默认基线。
- **可选 / 未接管主路径**：计划七闸引擎仅由默认关闭的可选段接入。
- **规划中 / 未实现**：计划澄清闸门、审批超时策略、飞书壳账号数据归并等。
- **已知缺口**：Debug Console 无多用户隔离、移动端 3 个 golden 漂移等（见 `evidence.md` §8）。

## 生成方式与限制

- 本环境未安装 Graphviz CLI，因此未生成 `.svg`；`.dot` 是规范源，建议用 Qoder 的 DOT 格式查看器预览。
- 若需要在 CI 中校验：安装 Graphviz 后运行 `dot -Tsvg <file>.dot -o <file>.svg`；Structurizr DSL 可用官方 CLI / Playground 解析。
- 修改架构时：先更新 `docs/current-system-architecture-baseline.md`，再同步本目录的 DSL / DOT，避免模型与基线漂移。
