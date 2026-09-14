# TOOL-009 Task Detail — Reflection Integration

> 上游：[../architecture.md](../architecture.md) §7.5（Tool 与 Reflection 集成）、§8.2（逐系统契约表）；[../tasks.md](../tasks.md) TOOL-009
> 状态：设计稿（未实现）
> 范围红线：**不新建反思机制**（复用既有三道闸与证据窗聚合）；工具证据**零豁免**（与用户证据走完全相同的闸门）；**反思不自动熔断工具**（反思管认知，健康度管运维，两通道互不越界）。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-009 |
| **Task Name** | Reflection Integration |
| **Priority** | P2 |
| **Dependencies** | TOOL-003 |
| **建议提交** | `feat: V2.4.0 工具效能反思证据源` |

## 1.1 Goal

让反思**分析工具效能**，而非只分析对话内容。在既有证据窗聚合器上扩三个证据窗（工具使用效果 / Action 成功率 / 用户反馈），复用既有 reinforce 计数与三道闸，产出可反哺决策与自治的 Insight。

同时明确一条边界：**反思不自动熔断工具**。工具的健康度熔断（TOOL-003）是运维机制，反思是认知机制——两者独立，互不越界。

## 1.2 Scope

**包含**

- 扩展 `app/services/reflection/evidence.py`：三个工具效能证据窗。
- 扩展 `app/services/reflection/triggers.py`：工具证据的 reinforce 计数接入（复用既有机制）。
- 扩展 `app/character/asuna/evaluation.py`（或反思资产模块）：工具效能 Insight 的判定规则与类型。
- 扩展 `app/services/reflection/reflector.py`：Insight 产出类型支持（只增类型，不改闸门）。
- 单测：三窗场景、证据门槛、三道闸零豁免、隔离断言（不改变注册表状态）。

**不包含（Non-Scope）**

- 反思触发机制改动（周期 + 事件双触发、三道闸**零改动**）。
- 自动熔断工具（明确不做）。
- 性格 / 人格类 Insight（工具故障不改变人格）。
- 关系域信号（TOOL-008 已声明 Non-Goal；Q8 留后续）。
- 工具实现体（TOOL-010）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 |
|---|---|---|
| `app/services/reflection/evidence.py` | 扩展 | 三个工具效能证据窗 |
| `app/services/reflection/triggers.py` | 扩展 | 工具证据 reinforce 计数接入 |
| `app/services/reflection/reflector.py` | 扩展 | Insight 类型支持（只增类型） |
| `app/character/asuna/evaluation.py` | 扩展 | 工具效能判定规则资产 |
| `services/memory2/sources.py` | 复用不改 | `fetch_action_records` 已提供工具执行投影 |
| `services/action/registry.py`（健康度） | **只读，且不写入** | 隔离断言对象 |

**证据窗图**

```text
工具执行（action_records.steps[].result = ToolResult）
        │
        ├─► 窗口一：工具使用效果
        │     按 tool_id 聚合成功/失败/超时 + observations 摘要
        │     → 偏好类 Insight（"用户连续取消后重设提醒 → 时间表述需更精确"）
        │
        ├─► 窗口二：Action 成功率
        │     按 action_type / tool_id 分组统计失败率 + failure_kind 分布
        │     → 能力自省类 Insight（"天气接口近一周失败 5 次 → 该能力当前不可靠"）
        │
        └─► 窗口三：用户反馈
              工具执行后 N 轮内的用户消息情感极性 + 是否撤销操作
              → 校正类 Insight（"我发的提醒消息用户从不回应 → 减少此类主动工具"）
        │
        ▼
既有三道闸（零豁免）
   证据门槛（passes_gate）→ 当日额度 → 幂等入队（job_key）
        │
        ▼
Insight 产出（既有生命周期）
        │
        ▼
只读反哺（三条通道，均不写工具状态）
   ├─ 决策侧：Insight 作 interest 维输入信号
   ├─ 自治侧：Insight 影响候选收缩
   └─ 人工面：调试端点可见，供运维决定是否熔断
```

## 2.2 数据结构

### 证据窗定义

| 窗口 | 聚合键 | 证据字段 | 触发条件 |
|---|---|---|---|
| `tool_usage_effect` | `tool_id` | `{success_count, failure_count, timeout_count, last_used_at, sample_observations}` | 同 tool_id 执行数 ≥ 门槛 |
| `action_success_rate` | `action_type` 或 `tool_id` | `{total, failed, failure_kinds: {kind: count}, window_days}` | 失败数 ≥ 门槛 |
| `user_feedback_signal` | `tool_id` | `{executions, followup_negative, revoked_after, silence_after}` | 样本数 ≥ 门槛 |

### Insight 类型扩展（只增类型）

| 类型 | 含义 | 证据来源 |
|---|---|---|
| `capability_note` | 能力可靠性自省 | 窗口一 + 窗口二 |
| `usage_preference` | 工具使用偏好 | 窗口一 + 窗口三 |
| `interaction_calibration` | 交互方式校正 | 窗口三 |

**纪律**：**不新增**性格 / 人格 / 关系类 Insight 类型（工具证据不产生这些）。

### 证据包结构（扩展既有）

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool_windows` | dict | 三个窗口的聚合结果 |
| `existing_windows` | dict | 既有窗口（对话 / 记忆 / 世界 / 关系）**原样保留** |
| `passing` | int | 过门槛的窗口数（既有语义） |

## 2.3 核心流程

### 证据聚合扩展

```text
aggregate_evidence_windows(user_id, character_id, now, trace)
    ├─ 既有窗口（对话 / 记忆 / 世界 / 关系）—— 零改动
    ├─ 新增：tool_usage_effect（从 action_records.steps 投影）
    ├─ 新增：action_success_rate（按 action_type / tool_id 分组）
    └─ 新增：user_feedback_signal（工具执行后 N 轮的用户消息）
        │
        ▼
    passes_gate（既有门槛函数，新增三窗的判定规则）
```

**数据来源纪律**：全部从 `action_records` **投影**读取（`memory2/sources.py::fetch_action_records` 已提供该能力），**不读工具注册表状态**、不读健康度内存态——反思看的是"历史执行事实"，不是"当前运维状态"。

### 失败驱动策略更新链

```text
Tool Failure（steps[].result.status ∈ {failed, timeout}）
        │
        ▼
证据聚合（同 tool_id 同 failure_kind 计数）
        │
        ▼
reinforce 计数达阈值（复用 REF-003 既有机制与冷却窗）
        │
        ▼
三道闸（零豁免）
   ① 证据门槛：样本数 / 时间跨度达门槛，否则 skipped（0 LLM）
   ② 当日额度：queued/running/done 占额（既有）
   ③ 幂等入队：job_key = reflect:user:日桶（既有）
        │
        ▼
Reflection 产出 Insight
   {type:"capability_note", content:"最近天气接口不稳定，先别急着查", confidence}
        │
        ▼
只读反哺（**不写工具状态**）
   ├─ decision_pipeline：Insight 作 interest 维输入
   ├─ autonomy_policy：Insight 影响候选收缩
   └─ debug 端点：人工可见
   ✗ 禁止：改 ToolRegistry 状态、改健康度、自动熔断
```

### 边界隔离（本任务的核心纪律）

| 机制 | 归属 | 输入 | 输出 | 越界后果 |
|---|---|---|---|---|
| 健康度熔断（TOOL-003） | 运维 | 执行结果计数 | 注册表 `tripped` → 工具面剔除 | 立即生效，确定性 |
| 反思 Insight（本任务） | 认知 | 历史证据窗 | Insight（软信号） | 缓慢生效，概率性 |

**两者不得互相调用**：反思**不读**健康度内存态，健康度**不读** Insight。隔离由测试强制（§6.2）。

## 2.4 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `services/reflection/evidence.py::aggregate_evidence_windows` | 追加三窗，既有窗口零改动 | 增量 |
| `services/reflection/evidence.py::passes_gate` | 新增三窗判定规则 | 增量 |
| `services/reflection/triggers.py::trigger_for_user` | 工具证据 reinforce 计数接入 | 增量 |
| `services/reflection/reflector.py` | 新增 Insight 类型支持 | 增量 |
| `services/reflection/lifecycle.py` | Insight 生命周期**零改动** | 零改动 |
| `services/memory2/sources.py::fetch_action_records` | 只读复用（已含终态过滤） | 零改动 |
| `services/decision_pipeline.py::_interest` | Insight 作输入信号（TOOL-004 已改该函数，本任务追加信号） | 增量 |
| `services/autonomy_policy.py` | Insight 影响候选收缩（TOOL-006 已加 `tool_facts`，本任务不冲突） | 增量 |
| `services/tool/registry.py`（健康度） | **只读禁止**——隔离断言对象 | 零改动 |
| `services/reflection/evaluation.py` | 离线评估场景扩展（新增工具效能场景） | 增量 |

**与 V2.3.0 世界证据窗的关系**：V2.3.0 已把世界事件摘要接入反思证据窗（WS-015）。本任务追加的是**工具效能**窗，与之并列——两套窗口独立聚合，共同经同一道闸门。

---

# 3. Database Changes

**本任务无任何数据库变更。**

| 项 | 结论 | 说明 |
|---|---|---|
| Table | 无新增 | 复用 `reflection_runs` / `insights` / `evidence_links`（V2.0 既有） |
| Field | 无新增列 | 工具证据窗是聚合结果，不落表；Insight 类型是代码值域扩展 |
| Index | 无新增 | 聚合走 `action_records` 既有查询与其既有索引 |
| Migration | **无** | — |

**Insight 类型扩展是值域扩展**（`type` 为既有自由域 / 受控值域），无结构变更——与 V2.3.0 `world_events.type` 值域扩展同款处理。

---

# 4. API / Interface Design

## 4.1 证据窗接口

```text
interface ToolEvidenceWindows:
    aggregate_tool_usage(user_id: str, *, now: datetime, window_days: int) -> dict
    aggregate_success_rate(user_id: str, *, now: datetime, window_days: int) -> dict
    aggregate_user_feedback(user_id: str, *, now: datetime, followup_turns: int) -> dict
    passes_tool_gate(window: dict, thresholds: dict) -> bool
```

| 项 | 内容 |
|---|---|
| **Input** | `user_id` + 时刻 + 窗口参数 |
| **Output** | 聚合 dict（见 §2.2） |
| **失败形态** | 聚合异常 → 返回空 dict + 日志（**按门槛未过处理**，与既有证据聚合同款纪律） |
| **纪律** | 纯读、零 LLM；**禁止**读 `ToolRegistry` / 健康度 |

## 4.2 判定规则接口（资产层）

```text
interface ToolInsightRules:
    insight_type_for(window_kind: str) -> str        # 窗口 → Insight 类型
    thresholds_for(window_kind: str) -> dict         # 门槛（样本数 / 时间跨度）
    is_personality_affecting(window: dict) -> bool   # 恒 False（防御性断言）
```

**`is_personality_affecting` 恒返回 `False`** 是一条防御性设计：把"工具证据不得产生人格类 Insight"固化为可测试的接口契约，而非依赖实现者记忆。

## 4.3 反哺接口

```text
interface ToolInsightFeed:
    interest_signal(user_id: str) -> list[dict]      # 供 decision_pipeline._interest 读取
    autonomy_signal(user_id: str) -> dict            # 供 autonomy_policy 读取
    # ⚠ 无 write_registry / trip_breaker 类方法（接口层面禁止越界）
```

**接口即边界**：反哺接口**只提供读方法**，从 API 形状上排除"反思改工具状态"的可能。

---

# 5. Implementation Plan

## Step 1 — 三个证据窗聚合

1. 实现 `aggregate_tool_usage`：按 `tool_id` 聚合成功/失败/超时 + observations 摘要（有界）。
2. 实现 `aggregate_success_rate`：按 `action_type` / `tool_id` 分组，含 `failure_kind` 分布与时间窗。
3. 实现 `aggregate_user_feedback`：工具执行后 N 轮用户消息的极性 + 撤销检测 + 沉默检测。
4. 单测：三窗各两用例（达门槛 / 未达门槛）；数据全部来自 `action_records` 投影；零 LLM 断言。

## Step 2 — 门槛、reinforce 与 Insight 类型

1. 实现 `passes_tool_gate` 三窗判定规则。
2. 接入 `triggers.py` 的 reinforce 计数（复用既有机制与冷却窗，**不改触发逻辑**）。
3. 扩展 `reflector.py` 的 Insight 类型支持（`capability_note` / `usage_preference` / `interaction_calibration`）。
4. 单测：证据不足 → `skipped` 且 0 LLM；三道闸零豁免（构造被拒场景）；幂等入队。

## Step 3 — 只读反哺与隔离验证

1. 实现 `interest_signal` / `autonomy_signal`（只读）。
2. 接入 `decision_pipeline._interest` 与 `autonomy_policy`（增量信号，缺省行为不变）。
3. **隔离断言测试**：反思全流程跑完后，`ToolRegistry` 状态、健康度、工具面**逐字节未变**。
4. 扩展离线评估场景（工具效能）。
5. 回归：Flag 全 off 时证据聚合与 V2.3.0 逐字节一致。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- 三个证据窗各有达门槛 / 未达门槛用例；未达门槛时**零 LLM 调用**（打桩断言）。
- 聚合数据**全部来自 `action_records` 投影**；不读注册表、不读健康度（导入与调用双向断言）。
- `passes_tool_gate` 三窗规则正确：样本数不足 / 时间跨度不足均判不过。
- reinforce 计数达阈值才触发；冷却窗内重复证据不重复触发（复用既有机制行为一致）。
- 三类 Insight 产出正确：`capability_note` / `usage_preference` / `interaction_calibration`。
- `is_personality_affecting` 恒返回 `False`（防御性契约测试）。
- 反哺信号可被 `_interest` 与 `autonomy_policy` 读取；缺省（无 Insight）时行为不变。

## 6.2 Integration Acceptance

- **隔离断言（核心）**：完整反思流程跑完后，`ToolRegistry.effective_status` / 健康度 / 工具面输出**逐字节未变**——反思不熔断工具。
- **接口层面隔离**：反哺接口无任何写方法（API 形状断言）；反思模块零导入 `services/tool/registry.py` 的写方法。
- 三道闸**零豁免**：工具证据与用户证据走完全相同的门槛 / 额度 / 幂等逻辑（同一函数调用路径断言）。
- `reflection/lifecycle.py` 零 diff；`reflection/triggers.py` 的触发逻辑零 diff（仅追加证据源）。
- 既有窗口（对话 / 记忆 / 世界 / 关系）聚合行为零变化（对照测试）。
- **Flag 全 off 时**：证据聚合与 V2.3.0 逐字节一致；既有反思测试零修改通过。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | 无任何工具执行记录 | 三窗全空；`skipped` 且 0 LLM |
| E2 | 单次工具失败（样本 1） | 未达门槛 → 不产 Insight（防单点噪声） |
| E3 | 同 tool_id 失败但 `failure_kind` 各不相同 | 按 `failure_kind` 分别计数，各自独立判门槛 |
| E4 | 证据聚合抛异常 | 按门槛未过处理（返回空 + 日志），不阻断反思主流程 |
| E5 | 当日额度已满 | 不产 Insight、不产新行（既有行为，防行膨胀） |
| E6 | 幂等键命中（同日重复触发） | 不重复入队（既有行为） |
| E7 | 工具失败后用户在下一轮表达不满 | 窗口三检出负反馈；与窗口二独立计数，可能各产一条 Insight |
| E8 | 工具失败但用户下一轮无任何消息 | 计入 `silence_after`（沉默信号），不误判为负反馈 |
| E9 | 用户撤销了工具产生的效果（如取消提醒） | 计入 `revoked_after`，窗口三加权 |
| E10 | 工具执行后 N 轮内用户消息极性中性 | 不计正也不计负（避免噪声） |
| E11 | 反思产出 Insight 后工具再次成功 | Insight 不自动撤销（认知不追运维）；由既有 Insight 生命周期管理 |
| E12 | 人为尝试让反思改注册表状态 | 接口无写方法 → 静态与运行期双重失败 |
| E13 | 离线评估中工具效能场景 | 场景可复现（注入式 runner），零真实调用 |
| E14 | V2.3.0 世界证据窗与本任务工具窗同时过门槛 | 各自独立入队（幂等键不同），额度共享（既有额度语义） |
