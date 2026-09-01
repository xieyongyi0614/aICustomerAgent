# V9 Action Model（行动域模型与生命周期）

> Action ≠ Response：本篇定义行动域的全部模型与六态生命周期。所有模型纯 Pydantic 零 IO（`app/models/action.py`），状态机为纯函数（非法迁移返回 None，V8 物品状态机同款纪律）。

## 1. 行动类型与来源

```python
ActionType = Literal[
    "create_reminder",     # 提醒/日程（→ WorldEvent type=reminder/appointment）
    "cancel_reminder",     # 取消既有提醒（→ cancel_events_by_type）
    "remember_fact",       # 显式记忆委托（"记住我生日是 7 月 30 日" → memories）
    "create_object",       # 获取/创建物品（"买牛奶" → WorldObject）
    "move_object",         # 移动物品（→ move_object）
    "use_object",          # 使用/消耗物品（→ apply_object_action）
    "query_environment",   # 环境查询（天气/光照/温度 → WorldEnvironment 读）
    "query_search",        # 信息检索（接口预留，MVP unavailable）
    "send_notification",   # 通知（接口预留，MVP 落行动 note）
]
ActionSource = Literal["conversation", "autonomy", "cancel"]
```

- `conversation`：前台对话检出（第 9 步）。
- `autonomy`：自治链路产出（`autonomy_action_enabled` 门控，默认关）。
- `cancel`：对既有行动的显式取消（"算了不用提醒了"）——原 ActionRecord 已终态不可变（审计原则），取消本身是**新行动**，`target_record_id` 指向原记录。

## 2. 模型总览

| 模型 | 生命周期 | 持久化 | 说明 |
|---|---|---|---|
| `ActionIntent` | 单轮内存 | 否 | 检出产物（候选），未过闸门前不是行动 |
| `ActionPlan` | 内存 + 内嵌于 Record | 随 Record | 闸门通过后的执行计划 |
| `ActionStep` | 内存 + 内嵌于 Record | 随 Record | 单个能力调用（MVP 恒 1 步） |
| `ActionResult` | 内存 + 内嵌于 Record | 随 Record | 执行产物：成败 + 效果清单 |
| `ActionEffect` | 内嵌于 ActionResult | 随 Record | 单项副作用（世界/记忆/关系/note） |
| `ActionRecord` | 跨轮持久 | **是**（action_records） | 行动审计聚合根 |
| `CapabilityResult` | 单次调用 | 随 Step | 能力层返回值（success/failed/timeout/unavailable） |

### ActionIntent（检出候选）

```python
class ActionIntent(BaseModel):
    action_type: ActionType
    confidence: Literal["confident", "ambiguous"]   # 词表命中 + 参数完整度
    params: dict            # 参数草稿（内容/时间短语原文/物品名/目标地点…）
    missing_params: list[str]   # 缺失参数名（ambiguous 时不执行，供澄清）
    evidence: str           # 命中的触发词/短语（≤40 字，评估证据）
    dedupe_key: str         # 幂等键：规范化(类型+核心参数) 摘要
    trigger_source: Literal["lexicon"]   # MVP 仅词表；llm_assist 预留
```

### ActionPlan / ActionStep

```python
class ActionStep(BaseModel):
    index: int
    capability: str                      # registry 能力名（reminder / memory / …）
    action: str                          # 能力内动作（create / cancel / query / …）
    params: dict                         # 装配后最终参数（schema 校验通过）
    status: Literal["pending", "executing", "succeeded", "failed", "skipped"]
    result: dict | None = None           # CapabilityResult 摘要（含 usage）

class ActionPlan(BaseModel):
    intent: ActionIntent                 # 来源意图快照
    goal_id: str | None                  # V6 动机来源（可空）
    steps: list[ActionStep]              # MVP 恒 1 步（action_plan_max_steps=1）
    expires_at: datetime | None          # 计划有效期（超时未执行 → cancelled）
```

### ActionResult / ActionEffect

```python
class ActionEffect(BaseModel):
    kind: Literal["world", "memory", "relationship", "note"]
    ref: str                  # 效果宿主引用：world_event_id / memory_id / relationship_event_id / note 文本
    detail: str               # ≤60 字人读摘要（"创建提醒 WorldEvent evt_xxx due 20:00"）

class ActionResult(BaseModel):
    status: Literal["succeeded", "failed", "partial"]   # partial 预留多步
    effects: list[ActionEffect]
    error: str | None         # 失败摘要（≤80 字）
    failure_kind: Literal["transient", "permanent", "timeout", "unavailable"] | None
```

### ActionRecord（持久化聚合根）

```python
class ActionRecord(BaseModel):
    id: str                            # act_{hex8}
    user_id: str
    character_id: str = "asuna"
    session_id: str | None             # 来源会话（autonomy 来源可空）
    source: ActionSource
    action_type: ActionType
    intent: dict                       # ActionIntent 快照
    goal_id: str | None
    target_record_id: str | None       # source=cancel 时指向原记录
    dedupe_key: str
    params: dict                       # 最终参数
    status: ActionStatus
    gate_reason: str | None            # 闸门否决原因（GateReason，cancelled 时必有）
    steps: list[dict]                  # ActionStep 快照（执行时回填）
    result: dict | None                # ActionResult 快照
    attempt: int = 1
    next_retry_at: datetime | None
    scheduled_at: datetime | None      # 创建的 WorldEvent due（create_reminder 时）
    created_at: datetime
    updated_at: datetime
    executed_at: datetime | None
```

## 3. 六态生命周期状态机

```text
                      闸门否决（G1~G6）
   created ──────────────────────────────► cancelled（gate_reason 必填）
      │ 六闸门通过 + 计划装配成功
      ▼
   planned ──超时未执行（expires_at 过期）──► cancelled
      │ ActionEngine 取出执行
      ▼
   executing ──能力全部成功──► succeeded（effects 回填）
      │ │
      │ └─不可重试失败（permanent/unavailable）──► failed（终态）
      └──可重试失败（transient/timeout）且 attempt < max
          │ next_retry_at = now + backoff
          ▼
        executing（attempt+1，同一 Record 复用）
```

- **created**：intent 检出即建 Record（含闸门否决路径——否决也是审计事实）。
- **planned**：闸门通过、steps 装配完成。created→planned 在第 9 步内瞬时完成（无独立排队等待，V7 ProactiveAction 的 candidate/approved 合并经验）。
- **executing**：executor 运行中；失败重试**不新建 Record**（attempt 递增、next_retry_at 退避）。
- **succeeded / failed / cancelled**：终态，不可迁移。已 succeeded 行动的撤销 = 新行动（ActionSource=cancel），原记录不改。
- 重试由 lifespan 维护循环（`run_action_retry_loop`，与 V8 `run_world_maintenance_loop` 同构）在 `next_retry_at` 到期时重新入执行；单进程内无并发竞争（per-user 写锁兜底）。

迁移表（`transition_action(status, event) -> ActionStatus | None` 纯函数）：

| 事件 | created | planned | executing | 终态 |
|---|---|---|---|---|
| gate_pass | planned | — | — | — |
| gate_reject | cancelled | — | — | — |
| execute_start | — | executing | — | — |
| step_all_succeeded | — | — | succeeded | — |
| step_retryable_failed | — | — | executing(attempt+1) / failed(超限) | — |
| step_permanent_failed | — | — | failed | — |
| expire | cancelled | — | — | — |
| cancel_requested | cancelled | cancelled | —（executing 不可取消，等待自然结束） | — |

## 4. CapabilityResult（能力层契约）

```python
class CapabilityResult(BaseModel):
    status: Literal["succeeded", "failed", "timeout", "unavailable"]
    payload: dict = {}        # 能力产物（world_event_id / memory_id / 查询结果…）
    usage: dict = {}          # 能力使用统计（duration_ms / source_provider…）
    error: str | None = None
```

- `unavailable`：能力已注册但后端未接入（search/notification MVP 形态）——**不算失败**，ActionRecord 置 failed(failure_kind=unavailable)，效果清单为空，评估降级为 info。
- payload 只携带 ID 与摘要，不携带宿主全量对象（世界/记忆详情一律经既有仓储读取）。

## 5. 与既有行动形态的边界

| | ActionRecord（V9） | ProactiveAction（V7） | WorldEvent（V8） | PendingAction（V3） |
|---|---|---|---|---|
| 回答的问题 | 执行是否真实发生 | 要不要主动说话 | 世界将发生什么 | 叙事动作进行到哪 |
| 状态机 | 六态（执行域） | candidate→acked（投递域） | scheduled→completed（事实域） | pending→completed（会话域） |
| 存储表 | action_records（0018） | proactive_actions（0011） | world_events（0017） | scene_states JSON |
| LLM 参与 | 无（全确定性） | 生成投递文本 | 无 | scene_update_chain 判定 |

- `create_reminder` 执行成功会**同时**产生一条 ActionRecord（succeeded + effect[world]）和一个 WorldEvent(scheduled)——前者是"做过"，后者是"会到期"。提醒到期触发的主动汇报走 V7 既有链路（autonomy-integration.md §2），不再产生新 ActionRecord（发消息是言语不是行动）。
- `ProactiveAction.type` 保持 `Literal["send_message"]` 不扩展——V7 队列语义（投递/ack/冷却）与执行域正交，泛化它需要重审八步闸门与前端协议，收益不抵回归风险。
