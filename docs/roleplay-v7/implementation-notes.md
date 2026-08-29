# V7 实现期说明与偏差记录

> 状态（2026-08-30）：V7-001~008（P0）+ V7-010/011（P1/P2）完成，全量回归 858 passed。
> V7-009（前端轮询展示）未做——实现指令明确禁止修改前端，后端 pending/ack API 已就绪，待前端窗口开放。

## 实现与设计的偏差（均为等价或加固，不改变语义）

1. **迁移编号**：设计写"迁移 0009"，实际为 **0011**（0009 已被 V4 memories 改名占用、0010 被 V6.5 conversations.mode 占用）；同时包含设计在 action-queue.md 提到的 `messages.is_proactive` 列（server_default=false，存量行为零影响）。
2. **状态机补充 `failed → approved`**：action-model.md §3 的"重新 approved"重试路径；Executor 锁内对 failed 且到期的行直接二次 approved。
3. **TOCTOU 加固**：Case 13（并发互斥）暴露"approved 迁移在锁外、用户复位 discard 与落库竞争"窗口 → `approved` 迁移移入 per-user 锁内并先重查 action 状态（action-queue.md §2 二次校验的本意）。
4. **dedupe 幂等收口到 repository**：设计预想的引擎内存 `seen_keys` 改为 `enqueue` 层拒绝（同 user 非终态存在或同 dedupe_key 未被 discard 即拒绝）——进程重启不丢幂等，单测可穷举。
5. **episode 起点**：聚合记账 episode_start = 用户最后一条消息时间（无记录则 epoch），对齐 cooldown.md §2；attempt 上限与退避均按此口径。
6. **tick 参数**：`run_autonomy_worker(tick_seconds=0)` 曾被 `or` 吞掉回落 60s——测试驱动需要 0 间隔，改显式 `None` 判断（教训：可配置参数禁用 `or` 兜底）。
7. **followup 登记点**：memory 管线冲突裁决之后、仅对实际入库（saved）记忆登记；关键词表（面试/考试/会议/答辩/体检）触发，due=次日 18:00；`resolve_batch` 异常提前返回时不登记（低频、丢失可接受，trigger-model.md §4 原话）。
8. **check_in 与反应式层的关系**：IntentionType 注册 check_in 并加入 intention_policy `_ALWAYS_VALID`；behavior_engine `INTENTION_STRATEGY_MAP` 保持 12 值不含 check_in（主动消息不走【表现方式】渲染，V6.5 对应测试同步收窄断言）。
9. **静音豁免接口**：`QUIET_HOURS_EXEMPT_TYPES = frozenset()` 空集实现（quiet-hours.md §4 留接口不实现）。
10. **时间注入**：Executor `execute(now=)` 与 Engine `tick(now=)` 显式注入——本地凌晨跑测试曾真实落入静音时段 discarded（时间相关逻辑必须可注入，V5 情绪衰减同款教训）。

## 已知非问题

- `tests/e2e/test_log_redaction.py` xdist 下 caplog 偶发空捕获（复跑即绿，V6.5 起既有）。

## 遗留待办

- V7-009 前端轮询与气泡展示（P1）：`GET /proactive/pending` 30s 轮询 + ack 上报，API 契约已固化（`tests/e2e/test_proactive_api.py`）。
- 真实回归人工执行（`regression-checklist.md`）：S1~S5 场景 + 开关对照；proactive prompt 的自然度调优依赖该数据。
- `FOR UPDATE SKIP LOCKED` 多实例竞争（V8）、Trigger 竞争排序 confidence（V8）。
