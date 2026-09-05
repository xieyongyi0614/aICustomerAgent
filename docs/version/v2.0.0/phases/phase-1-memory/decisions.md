# Phase 1 Implementation Decisions — 实现裁决记录

> Phase 1 实现过程中发现 Task Detail / design 与可执行口径存在 4 处冲突、1 处缺口。
> 全部按本文档记录的裁决落地（代码为准，本文档为唯一权威解释）；对应 Detail 已加指针。
> 后续 Phase（Reflection/Relationship 消费 memory2）必须沿本口径。

## D1 hypothetical 候选：直接 Rejected，不转正

- **冲突**：MEM-003 Detail 写「永不转正为 normal」（暗示可转正为 hypothetical 可见性）；
  design.md §4 状态机明确 `Candidate --> Rejected: 低于门槛/重复/hypothetical`。
- **裁决**：按状态机执行——hypothetical 候选不调 LLM、不写 memories，以
  `status=rejected, reason=hypothetical` 留痕在 memory_candidates（P2 Reflection 可查
  rejected 行做证据）。`memories.visibility=hypothetical` 在 Phase 1 不会出现，
  visibility 列保留供 P2+ 显式场景使用。
- **落点**：`memory2/evaluator.py` `_decide`。

## D2 LLM 兜底率窗口与候选失败计数的边界

- **冲突**：LLM 调用失败若计入兜底率窗口，窗口速率冲至 1.0 触发护栏熔断，5 次失败
  计数永远无法累积——tasks.md 的「max 5 后 rejected」验收不可达。
- **裁决**：滑动窗口只记录两类灰区样本——成功兜底（True）与护栏让位（False）；
  LLM 调用失败不占窗口，由候选级连续失败计数承接（达 `_LLM_MAX_FAILURES=5` 转
  `rejected(reason=llm_failed)`）。稳态兜底率 ≈ cap（0.3），故障期成本由 5 次上限兜底。
- **落点**：`memory2/evaluator.py` `_decide_gray_zone` / `_fallback_budget_available`。

## D3 decay 周期任务为全局日桶键

- **冲突**：MEM-009 Detail 写 job_key=`memory_decay:{user}:{date}`，但
  `run_decay_cycle` 是全局处理器（跨用户批处理衰减），按用户入队会 N 倍重复执行
  （虽被日桶幂等兜住，纯属浪费）。
- **裁决**：P1 采用全局日桶键 `memory_decay:{date}`，单用户单 job。P5 Life Loop
  引入多执行器/分片时再按用户拆分（届时 run_decay_cycle 需增加 user 过滤参数）。
- **落点**：`memory2/job_worker.py` `_enqueue_due_decay`。

## D4 多匹配遗忘结构性不可达（误删率 0 的来源）

- **冲突**：MEM-007 Detail 的 forget 门槛「唯一高匹配才删；多匹配 → 不删」中，
  「多匹配」分支与 MEM-005 冲突链矛盾——同主题多条 active 记忆在新记忆转正时即被
  supersede/merge 收敛，forget 时几乎必然 ≤1 个 active 匹配。
- **裁决**：保留多匹配守卫作为防御（匹配集含 decayed 行等场景），Eval 场景 ef-02
  改测「模糊指令（无高匹配目标）→ 不删」。多匹配结构性不可达本身即误删率 0 的
  系统性保障，验收按「不删除任何未指明记忆」口径执行。
- **落点**：`memory2/commands.py` `_handle_forget`；`tests/eval` explicit_forget.json。

## D5 v2 类型体系收口（7 规范 + 2 遗留，P2 前置）

- **缺口**：Phase 1 交付时类型仍为 v1 4 类 Literal，design.md §3 的 7 类体系未落地
  （P2 Reflection 的证据检索依赖 experience/relationship_fact）。
- **裁决**：迁移 0024 将 `ck_memories_type` 扩为「7 规范（user_preference/user_fact/
  experience/relationship_fact/commitment/milestone_event/behavior_pattern）+ 2 遗留
  （important_event/relationship_event）」共 9 值；v1 Pydantic `MemoryType` Literal
  同步放宽（向后兼容，既有 4 值行为不变）。v2 转正入口（`memory2/evaluator._final_type`）
  统一归一化：`important_event→experience`、`relationship_event→relationship_fact`
  （统一真相源裁决，relationship_fact 替代 v1 relationship_event 记忆类型）；
  遗留类型在检索亲和（retriever）与衰减 λ（lifecycle）处按别名归一。
  v1 Flag OFF 路径不受影响（golden 不变）。
- **落点**：`memory2/types.py`、`migrations/versions/0024_memory_v2_types.py`、
  `evaluator/_final_type`、`retriever/_AFFINITY_TYPE_ALIASES`、`lifecycle/decay_lambda_for`。
