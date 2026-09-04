# v2.0.0 Version Boundary（v1.0.0 ↔ v2.0.0 模块边界登记册）

> 原则：**v2.0.0 是 v1.0.0 的能力扩展，不允许无理由重写 v1。** 本文件逐模块裁决 Preserve / Extend / Replace / Deprecated，是所有 Task `Non-Scope` 的上游依据。
> 配套阅读：[migration/v1-to-v2.md](migration/v1-to-v2.md)（数据迁移）、[architecture/overview.md](architecture/overview.md) §4（结构差异清单）。

## 1. 裁决总表

| v1.0.0 模块 | 裁决 | v2.0.0 处置 | 涉及 Phase |
|---|---|---|---|
| `character/asuna/` 静态资产 | **Preserve** | 零改动；DevPolicy 只做参数注入，不改文件本体 | P3 |
| `character_state` + 情绪衰减（V5） | **Preserve** | 数学公式不动；State 域被 Development 调制的只有读取侧参数 | P1 读取信号、P3 调制 |
| `memories` 表 + `memory_service/memory_policy/memory_conflict` | **Extend + Replace(路径)** | 表扩列不改义；v2 新 `memory2/` 服务为 Flag 内替换路径，旧代码保留一个观察期后清理 | P1 |
| `relationships/relationship_evolution`（V8.5 六维引擎） | **Preserve** | D1/D2/D3/D5 数学、限速、迟滞零改动；v2 只加 Shared Experience 投影与 Patterns 读取 | P4 |
| `relationship_events` 账本 | **Preserve** | 仍是数值唯一真相源；叙事事实转写由 Memory Ingest 完成（Relationship 域不直写 memories） | P4 |
| `goals` + `goal_service`（4 类扁平） | **Extend** | 扩列 parent_goal_id/layer/domain/failure_reason；旧 4 类语义与行为保持；P6 加层级/Planning | P6 |
| `intention_chain` / 13 intention | **Replace(语义归并)** | Intention 降级为 Decision 域值对象输出；链本体在 P1/P2 期间不动（归并在 LLM Orchestration 重构中执行） | LLM 重构（横切） |
| `action/*`（V9 detector→planner→executor→registry） | **Extend** | 引擎零改动；默认启用由 `v2_action_outbox_enabled` 子闸承载 | P5 |
| `worlds/world_entities/world_events/world_snapshots`（V8） | **Preserve** | 域模型与规则解释器不动；只新增 outbox 消费入口 | P5 |
| `application/chat_pipeline` + `post_process` | **Extend** | 步骤级改造（抽取步骤替换为 ingest 调用、模型分层接线），编排结构不变 | P1 |
| `context_builder` + prompts | **Extend** | 扩展为 Context Architect 五策略；12000 预算与分段结构沿用 | P1 检索段、横切 |
| `llm_factory` + 11 条 chain | **Extend** | 增加按任务取 profile 的两档分层；链合并在 Flag 内渐进执行 | 横切 |
| autonomy_engine / autonomy_worker（60s tick + 内存 Trigger Registry） | **Replace(执行器)** | P5 归并入 Life Loop Controller；触发判定纯函数（AutonomyPolicy）本体保留 | P5 |
| 5 个 lifespan 常驻 asyncio 循环 | **Extend→Replace** | P1 加 background_jobs 表；P5 归并为统一调度；单进程模型在 R14 阈值前不变 | P1/P5 |
| runtime_traces / llm_call_records / prompt_snapshots / decision_records | **Extend** | 新增 memory/reflection/goal trace 步骤，复用 trace_collector，不新建存储 | 全部 |
| Evaluation Engine（V7.5 规则 + Judge） | **Extend** | 注册表式扩展（memory/reflection/development/relationship/goal/autonomy 规则集），不再线性堆积 | 全部 |
| `world_llm_assist` / `rel_signal_llm` | **Deprecated(维持默认关)** | v2 不启用、不删除；随 3.0 一并裁决 | — |
| v9 整链路（action_enabled=False 出厂） | **Extend** | 由 P5 子闸灰度启用，启用即默认开 | P5 |

## 2. 明确不 Preserve 的理由记录

- **memory 检索路径 Replace**：字符级关键词打分无法满足「改述召回」完成标准，但替换走双路径 Flag 切换而非删除，回滚零成本。
- **Trigger Registry 内存 dict Replace**：重启即丢是 v1 审计确认的持久化缺口，P5 表化。
- **forget 硬 DELETE Replace**：改为软删 + 保留期（data-flow.md §2.2），防误删不可恢复。

## 3. 禁止事项（对所有 Task 生效）

1. 任何 Task 不得修改本表标注 **Preserve** 的模块的数学/资产/域模型。
2. 任何 Task 不得删除 v1 代码路径（清理统一在 v2 全量稳定一个版本后单独执行）。
3. 任何 Task 不得改 `docs/version/v1.0.0/`。
