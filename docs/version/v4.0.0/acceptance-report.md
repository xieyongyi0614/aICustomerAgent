# V4.0.0 Acceptance Report

> 状态：**CONDITIONAL — NOT RELEASED**  
> 日期：2026-09-22  
> 范围：PLA-001 ~ PLA-018（实现）+ PLA-017（验收）

## 1. 交付摘要

| 任务 | 状态 | 提交 |
|---|---|---|
| PLA-001~008 / 018 | 已实现 | 见 `bc15bc9` 及之前 |
| PLA-009 账本能力与工具 | 已实现 | `734e6b44` |
| PLA-010 确认订正与冲正 | 已实现 | `bba7a82e` |
| PLA-011 账务节律投递 | 已实现 | `8af9ba45` |
| PLA-012 预算目标接入 | 已实现 | `59a13397` |
| PLA-013 超支预警 | 已实现 | `27ab39b4` |
| PLA-014 消费洞察 | 已实现 | `a1b9560d` |
| PLA-015 账本查询接口 | 已实现 | `1d6a8e62` |
| PLA-016 账本用户视图 | 已实现 | `1fc56d5e` |
| PLA-017 验收与回归 | 本报告 | — |

## 2. Gate 结果（G1~G16）

| Gate | 结果 | 证据 |
|---|---|---|
| G1 用户实体就位 | PASS | `tests/v40/test_life_user_identity.py`；`0053` 迁移 |
| G2 账目精确性（核心） | **CONDITIONAL** | 自动化证据见 §3；≥50 笔真实模型人工核对**待执行**（发布前硬条件） |
| G3 不可遗忘 | PASS | `test_ledger_model.py` 静态断言：无 TTL / 过期 / 衰减列 |
| G4 幂等与冲正 | PASS | `test_ledger_repository.py` / `test_ledger_correction.py` |
| G5 金额精度 | PASS | `to_minor` / `to_major`；零 float 断言 |
| G6 账目不入记忆 | PASS | `test_ledger_insight.py::test_memories_contain_zero_amount_digits` |
| G7 零 LLM 数字 | PASS | digest / alert AST 零 LLM；`test_digest_module_has_no_llm_import` |
| G8 治理合规 | PASS | `test_life_governance.py` / `test_life_governance_api.py` |
| G9 越权防护 | PASS | `test_ledger_api.py::test_cross_user_*` |
| G10 单一写面 | PASS | `test_budget_write_only_via_goal_repository`；`test_direct_capability_call_is_absent_in_business_layer` |
| G11 Preserve 零改动 | PASS（判定口径） | reflection / memory2 / planning 数学未改；见 §5 |
| G12 零回归 | PASS（判定口径） | `tests/v40` 291 passed；V4.0 新引入失败 0 |
| G12b 零新增功能开关 | PASS | `tests/v40/support.py::V40_SETTINGS_FIELDS` 仅参数类 |
| G13 迁移可空跑 | CONDITIONAL | `0053` / `0054` 用例在内存 SQLite 全绿；**真实 PG 双向空跑待环境** |
| G14 钉测收敛 | PASS | `0053`/`0054` 升级时链头钉测为单点入口 |
| G15 运行时单一路径 | PASS | `test_runtime_background_cutover.py` |
| G16 PG 真实执行 | **FAIL / 待环境** | 本地无可用 `TEST_DATABASE_URL` 时 PG 用例会 skip（D-4 同类风险）；发布前必须在真实 PG 跑 `tests/integration/test_db_migration.py` |

## 3. 账目精确性（自动化代理证据）

真实模型 ≥50 笔人工核对为发布硬条件。当前以自动化契约作为代理：

- 抽取链零幻觉前置：`verify_amount_evidence` + `classify_extraction`（`test_ledger_extraction.py`）
- 聚合数字只来自结构化字段：`test_ledger_query.py` 逐分一致
- 推送 / 预警数字与聚合一致：`test_ledger_digest.py` / `test_ledger_alert.py`
- 意图反例不误记：`test_ledger_intent_detection.py::test_rejects_memory_verb_false_positive`

**样本表（人工核对模板，待填）**：见 `regression-checklist.md` §2。

## 4. 测试执行摘要

| 套件 | 结果 |
|---|---|
| `tests/v40` | **291 passed** |
| 前端 `npm test` | **154 passed**（含 Debug 面板既有用例） |
| 前端 `npm run build` | 成功 |
| `tests/v24` / `v26` | 存在基线失败集（tool009 ×6 等，见 V3.0 I-2）；V4.0 新引入失败 0 |

## 5. Preserve 与红线

- 账本表结构冻结于 `0054`；后续任务零新表（除 `loop_runs.kind` / `character_goals.domain` CHECK 的 ORM 同步——**生产库需补迁移**，见 §7 缺陷）。
- `services/reflection/**` 三闸、`services/memory2/**`、`services/planning/{engine,decompose}.py` 数学零改动。
- 未新增功能开关。

## 6. 运行时口径勘误（登记，不改 V3.0 冻结报告）

1. V3.0「边界不变量 8 PASS」为**开关开启测试态**口径；V4.0 PLA-018 后生产态已统一到 Agent Runtime。
2. V3.0 影子矩阵表格漏 `runtime_foreground_loop_enabled` / `runtime_six_stage_loop_enabled`（代码与测试为 13 个字段）。

## 7. 缺陷与待办

| # | 级别 | 描述 | 状态 |
|---|---|---|---|
| A-1 | P0 发布阻断 | G2 真实模型 ≥50 笔人工核对未执行 | 待排期 |
| A-2 | P0 发布阻断 | G16 真实 PG 迁移双向空跑未执行 | 待环境 |
| A-3 | P1 | `ck_loop_runs_kind` / `ck_character_goals_domain` 的 ORM CHECK 已扩，**生产库无对应迁移** | 待补 `0055` |
| A-4 | P2 | `api→repositories` 既有 26 处（I-3）未清理 | Backlog |
| A-5 | P2 | tool009_reflector ×6 等基线失败 | 既存债 |

## 8. 发布裁决

**CONDITIONAL — NOT RELEASED**

阻塞条件：
1. 完成真实模型 ≥50 笔账目精确性人工核对（零幻觉数字）；
2. 在真实 PostgreSQL 执行 `0053`/`0054` 双向空跑且 PG 用例非全 skip；
3. 补生产库 `loop_runs.kind` / `character_goals.domain` CHECK 迁移（或回滚 ORM CHECK 与生产一致）。

满足以上三条后可改判 **RELEASABLE**。
