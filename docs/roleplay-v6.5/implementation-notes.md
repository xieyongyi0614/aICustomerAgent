# V6.5 实现期说明与偏差记录

> 状态（2026-08-29）：V6.5-001~007（P0 全部）已实现，全量回归 765 passed；V6.5-008~012（P1/P2）待后续。
> 迁移 0010 已在本地 PG（127.0.0.1 asuna 库）执行：0009 → 0010，存量会话行回填 mode=default。

## 实现与设计的偏差（均为等价或收窄，不改变语义）

1. **ActivityPresence 枚举值命名**：设计文档写 `ambient / engaged / pending`，实现取 `ambient_activity / engaged_action / pending_obligation`（behavior-strategy.py `ActivityPresence`），与 V3 字段语义对齐，代码内自洽。
2. **HabitRule.condition**：保留为声明式描述字段（渲染不用、匹配不用）；MVP 适用性由引擎 `HABIT_APPLICABILITY` 域表驱动（habit-system.md §4 原意）。
3. **同向 habit 去重位置**：设计写在渲染层（response-controller.md §3.1），实现移到引擎 `match_habits`（`HABIT_SAME_DIRECTION` 表），渲染层简化，效果等价且可单测。
4. **Budget 数字的渲染位置解读**：设计要求「同一约束一个数字」。实现为：【表现方式】段含 budget 短句；RHYTHM 动作行同步替换为同值表述（不再出现默认「0~2」与预算值并存）。两处数字恒一致、角度互补（中段方向约束 / 尾部节奏清单），不构成两个互相冲突的数字。
5. **router 低置信语义转移**：原 `router_confidence_threshold`（0.5）的「降级 default」职责由稳定器承接——低置信候选（conf < 0.7）经 R3 永不切换；该阈值仅保留 trace `role_router: degraded` 标注用途。R5 由「router 故障 → 空候选」表达（chat_pipeline `_router_candidate` 返回空串）。
6. **physical_contact 的 min 语义解释**：非 affectionate 策略同样取 stage 档 contact 值（如 partner 档日常对话允许「递东西」类轻度动作）；professional 恒 none。 affectionate_expression 不额外放宽（stage 档即上限，最高 light）。
7. **test_behavior_consistency.py 未建独立文件**：Case 1~3 由 `tests/unit/test_behavior_engine.py`（确定性/修饰矩阵）与 `tests/e2e/test_v65_matrix.py::test_case1_strategy_trajectory_reproducible / test_case3_tension_modifier_passthrough` 承担，覆盖等价。
8. **context_builder 复用 ensure_conversation 返回行**：原实现 ensure 后再 `find_conversation` 二次查询，收尾时合并为一次（设计 architecture.md §5「零额外查询」的本意）。

## 已知非问题

- `tests/e2e/test_log_redaction.py` 在 xdist 全量并行下 caplog 偶发捕获为空（与 V6.5 改动无关，单测与复跑恒绿）；如频发可考虑改为 `capfd` 或独立 marker。

## 遗留待办（对应 tasks.md P1/P2）

- V6.5-008 Debug/API 前端展示、V6.5-009 真实模型回归清单（`regression-checklist.md`）、V6.5-010 输出侧预算统计器、V6.5-011 动态 Habit、V6.5-012 V2 behavior 退役评估。
- 真实效果验证（动作描写是否收敛、strategy 观感稳定性）依赖 V6.5-009 的人工回归，FakeLLM 只能验证机制正确性。
