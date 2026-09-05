# Phase 1 Regression Checklist — Memory 2.0

> 目的：保证 Flag OFF 时 v1.0.0 行为**字节级不变**，Flag ON 时既有能力不回退。执行时机：每 Task 合入（分级测试：Focused → Module → 必要时 Fast 档）、每灰度推进（migration §6）、阶段收口（全量 pytest，执行前先汇报测试规模）。

## Golden 行为（绝对不许变化）

1. Flag OFF：记忆抽取/检索/遗忘全链 = v1 行为逐字节一致（prompt_snapshots 对比）。
2. Flag ON 但 `v2_memory_vector_enabled` OFF：仅结构化打分，输出与 v1 检索语义等价。
3. 前台 LLM 调用数 ≤ v1 基线（每轮 5 次）。
4. v1 memories 表既有行语义不变（扩列 NULL）。

## 必须重跑的旧版本回归

| 来源 | 范围 | 触发条件 |
|---|---|---|
| 分级测试（Focused → Module → Fast 档 `-m "(unit or api) and not slow"`） | 影响范围测试全绿 | 每 Task 合入 |
| V4 memory checklist（v1.0.0/v4/） | 记忆抽取/检索/冲突全项 | 每 Task 合入 |
| V7.5 evaluation checklist | evaluation 规则不回退 | 涉及 post_process 步骤的 Task |
| V7.8 trace/metrics checklist | trace 完整性 | MEM-008 |
| v1 全量 pytest | 基线 | 阶段收口 / 重大迁移（MEM-001 迁移基线已建） |

## 执行步骤

```text
1. 每 Task 合入：分级测试全绿（Focused → Module → Fast 档）；不默认跑全量
2. 阶段收口：Flag OFF 全量 pytest + golden 对比（字节级）
3. Flag ON 影子环境跑 V4 checklist
4. 迁移 up/down 往返 + 数据逐行对比
5. 结果记录至本文件附录（日期/环境/结论）
```

## 可执行入口（MEM-010）

| Gate | 命令 | 判定 |
|---|---|---|
| Eval Gate（Flag ON 影子态，确定性 stub） | `pytest tests/eval/test_memory_eval_gate.py` | E-MEM-01~06 达 evaluation.md 门槛，报告落 `apps/backend/tests/eval/reports/mem-{date}.json` |
| Regression Gate（Flag OFF golden 字节级） | `pytest tests/golden` | diff 为空 |
| 分级测试 | Focused（tests/v2）→ Module（tests/unit + tests/golden）→ Fast（`-m "(unit or api) and not slow"`） | 全绿 |
| 迁移往返 | `pytest tests/v2/test_mem001_foundation.py`（head=0023） | upgrade→downgrade→upgrade 数据逐行相等 |
| v1 全量 pytest | `pytest`（阶段收口先汇报规模） | 无新增失败 |

## 附录：执行记录

- 2026-09-06（feat/v2.0.0，MEM-010 合入）：Eval Gate 首跑 21 场景/10 类全过（E-MEM-01 1.0、02 1.0、03 1.0、04 1.0、05 1.0、06 1.0，probes 12 次零违例）；场景集为确定性种子集，标注规模随 Phase 累积（目标每类 ≥10）。本地环境注意：全量 e2e 存在与本 Phase 无关的时序敏感基线失败（已在 Phase 1 报告记录），分级测试口径全绿。
