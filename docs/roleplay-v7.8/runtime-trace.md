# M1 Runtime Trace System

> 目标：记录一次完整角色运行的全过程，回答"为什么角色这样回复 / 哪个模块导致异常 / 哪个状态发生变化"。
> 形态：**演进现有 `trace_collector`**，不重写。热路径行为与现状完全一致，新增的只有收尾后的持久化旁路。

## 1. 四个核心概念

| 概念 | 现状 | V7.8 定义 |
|---|---|---|
| TraceContext | `TurnTraceSession`（`app/services/trace_collector.py:69`） | 一次运行的活上下文：request_id、kind、身份键、steps/events 累积器、生命周期 begin → flush。**保留在内存，热路径不碰 DB** |
| TraceStep | `TraceStep`（已有） | 步骤记录：name / status / duration_ms / first_token_ms / error / extra。26 个步骤名注册表 `TRACE_STEP_NAMES` 不变 |
| TraceEvent | 无 | 新增：**状态变化点事件**（before → after），补足 step 只记"发生了什么调用"不记"状态怎么变"的缺口 |
| TraceStorage | 内存 LRU（容量 20，易失） | 两层：内存 LRU（现状不变，即时读）+ `runtime_traces` 表（write-behind，跨重启可查） |

## 2. TraceKind：三种运行主体

```text
turn           前台对话轮（现状已覆盖，002 持久化）
proactive      主动行为执行（现状完全无 trace，008 补齐）
autonomy_tick  自治决策 tick（产生决策才记，与 M2 联动，008 落地）
```

## 3. 域模型（`app/models/observability.py`）

### RuntimeTrace（持久化行 = snapshot）

| 字段 | 类型 | 说明 |
|---|---|---|
| trace_id | str | = request_id（uuid4 hex，既有） |
| kind | TraceKind | turn / proactive / autonomy_tick |
| user_id | int | |
| conversation_id | str \| None | autonomy_tick 可空 |
| turn_id | str \| None | AI 消息 id（关联主键，同 evaluation subject_id 源） |
| action_id | str \| None | proactive_actions outbox id |
| status | str | complete / degraded / error（沿用既有 step status 语义聚合） |
| started_at / duration_ms | datetime / int | |
| steps | list[TraceStep] | 既有结构，extra 有界（`observability_step_extra_max_chars`，默认 2000） |
| events | list[TraceEvent] | 新增，见 §4 |
| token_usage | dict | input / output / total（answer 链既有累加） |
| model_name | str \| None | |
| meta | dict | behavior_meta / mode_meta（既有，值有界） |

### TraceEvent

| 字段 | 类型 | 说明 |
|---|---|---|
| kind | str | emotion_change / mode_change / goal_change / relationship_change / scene_change |
| at_ms | int | 相对 started_at |
| payload | dict | before / after（有界）；如 `{"before": "neutral", "after": "happy", "trigger": "user_tired"}` |

## 4. 事件采集：后置读取，零侵入

事件**不在**各 service 内埋点（那会改六个系统），而是在两个只读位置后置采集：

1. **结果对象回读**：chat_pipeline 各步骤返回后，从返回值（mode_stabilize 的 mode、goal_selection 的 GoalContext、scene_resolver 的 SceneState）提取 before/after 追加为 event——只读，不改变调用。
2. **落库时回填**：sink 组装 snapshot 时从既有表读（emotion_history 的本轮 before/after 行、relationship_events 本轮新增行）——这些表 V4/V5 本来就在记，观测层只是换个视角读。

优先级：结果对象回读为准，回填仅补漏；两者都不改变任何业务写入。

## 5. TraceStorage：两层存储与持久化规则

```text
内存层（现状不变）：
  TraceCollector LRU(20)，key=turn_id，服务 /debug/turns/{id}/trace 即时读
持久层（002 新增）：
  runtime_traces 表，一次运行一行（steps/events/meta 全 JSON，V7.5 digest 先例：拒绝宽表）
```

持久化判定（Facade，turn 收尾后）：

```text
status ∈ {error, degraded}   → 必存（出问题的运行永远值得留）
否则                          → request_id sha256 确定性采样（observability_trace_sample_rate，默认 1.0）
开关关闭 / 写库失败           → 放弃本条，log，内存层不受影响
```

确定性采样沿用 `evaluation_engine.should_sample` 口径（request_id 哈希），**独立实现不共享代码**——两套采样率各自可调，互不耦合。

## 6. 查询 API

| 端点 | 行为 |
|---|---|
| `GET /debug/turns/{turn_id}/trace`（既有） | 先查内存 LRU，miss 则查 `runtime_traces`（turn_id 索引）；都没有 404——**现状语义不变，只是寿命从"重启即失"变为"TTL 内可查"** |
| `GET /debug/traces/{trace_id}`（002） | 按 request_id 直查持久层 |
| `GET /debug/traces?conversation_id=&window=`（002，P1 顺手） | 会话内运行列表（轻量摘要：status/duration/step 名单） |

## 7. 边界

- 不新增步骤、不改 26 个步骤名、不改任何 `trace.record` 调用点——步骤注册表原样。
- 内存 LRU 容量、淘汰策略不动；持久层不做实时查询优化（JSON 行 + 少量索引足够调试台场景）。
- autonomy_tick trace 不记 LLM 调用细节（tick 内无生成调用，生成在 executor 阶段，归 proactive trace）。
