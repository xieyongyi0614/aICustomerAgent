# AUTO-005 Task Detail — 主动消息投递链路闭合

## 1. Background

- **Phase 位置**：Autonomy 2.0（Phase 6）的 Phase 5「Autonomous Execution」，是整条 Autonomy 链路的**最高优先任务**，也是 `patch-tasks.md` 中 `PATCH-AUT-01` 的正式 Task Detail。
- **为什么需要**：v2.0.0 已把「何时触发、何时决策、何时生成」设计并实现，但「主动消息真正发到 Channel（Feishu）」这条投递链路**尚未闭环**。`proactive_executor.execute` 生成文本后只调用 `save_proactive_turn` 落库并置 `delivered`，**从未调用 `delivery.send_proactive`**。结果主动行为在内部被标记为「已投递」，实际并未触达用户——主动消息「空转」。
- **解决什么问题**：闭合「Decision → 生成 → 落库 → Feishu 真实发送」的完整链路（architecture.md Gap G1），同时澄清 `internal_message_id` 与 `external_message_id` 语义（G2），拆分生成/发送两阶段（G3）。

## 2. Goal

本 Task 完成后，角色产生的主动行为（如主动问候、约定提醒）能够**真实送达 Feishu**，且整个过程经过 Agent Runtime 与 Channel Adapter 的统一入口，具备可追溯、可幂等、可重试的能力。Autonomy 只产 Action Intent，文本生成走角色化生成链，投递走 `ChannelAdapter`。

## 3. Scope

**包含：**

- 新增能力：`proactive_executor` 在落库后调用 `delivery.send_proactive`，闭合投递链路。
- 修改模块：`services/proactive_executor.py`（执行期补投递）、`core/db.py` 的 `ProactiveActionRow`（增列）。
- 涉及数据结构：`proactive_actions` 增一列 `external_message_id`（nullable）；明确 `message_id` 语义为 `internal_message_id`。
- 系统边界：Autonomy 只产 Action Intent；文本生成走 `proactive_chain`；投递走 `ChannelAdapter`（`app.channels.base`）。

**不包含：**

- 不改 Chat Pipeline、不改 Feishu 模块、不改 Autonomy 决策逻辑、不改 Character 生成链。
- 不新增表、不新建队列/调度。
- 不实现多候选 LLM 软排序（G5）、偏好→重复提醒（G6）、新 Trigger 类型（G7）——均属未来版本。

## 4. Architecture Design

```text
Autonomy Decision(act)
  → ActionIntent(type=send_message, dedupe_key)
       ↓
proactive_executor.execute
  → proactive_chain.generate（角色化文本生成，可重试）
       ↓
conversation_service.save_proactive_turn（落库 messages，is_proactive=True）
  → internal_message_id
       ↓
delivery.send_proactive(internal_user_id, text, idempotency_key=dedupe_key)
  → channel_identity_service.resolve_recipient
  → FeishuChannelAdapter.send
  → client.send_message
       ↓
SendResult(external_message_id)
       ↓
回填 proactive_actions.external_message_id → 状态 = delivered
```

**两阶段边界（关键）：**

```text
生成阶段（可重试，失败 → 回 candidate / failed）
  ↓ 成功 → 落库 internal_message_id
发送阶段（可重试，失败 → 仅重发，不重生成、不重新裁决）
  ↓ 成功 → external_message_id 回填 → delivered
```

## 5. Data Model

```text
Entity: ProactiveAction（复用 proactive_actions 表，Outbox 语义）
Fields（新增/澄清）:
- message_id             internal_message_id（messages 表主键，save_proactive_turn 返回）
- external_message_id    Feishu 侧 message_id（SendResult.external_message_id），nullable，新增
- dedupe_key             幂等键，同时作为 OutboundMessage.idempotency_key 传递
- attempt / next_retry_at  重试计数与调度
- status                 状态机：candidate/approved/delivered/acked/discarded/failed/expired

Relation:
- message_id → messages.id
- external_message_id → Feishu 侧消息（外部，无本地外键）
```

> `delivered` 语义重定义为「Feishu 已成功投递」。内部落库由 `internal_message_id` 字段表达，二者解耦。

## 6. Core Logic

- **Step 1**：`proactive_executor` 对 approved action 执行前置二次校验（`_recheck_failed_reason`：用户是否已回来、是否静音、目标是否仍存在）。
- **Step 2**：生成阶段——调用 `proactive_chain.generate` 产出角色化文本；文本为空或目标消失视同生成失败，`_fail_for_retry` 重试，超限 → failed 终态。
- **Step 3**：落库阶段——`save_proactive_turn` 写入 messages（`is_proactive=True`），取得 `internal_message_id` 写入 `proactive_actions.message_id`。
- **Step 4**：发送阶段——调用 `delivery.send_proactive(internal_user_id, text, idempotency_key=dedupe_key)`；由 `resolve_recipient` 解析 `internal_user_id → (channel=feishu, external_id=open_id)`，经 `FeishuChannelAdapter.send` 发送。
- **Step 5**：回填阶段——`SendResult.external_message_id` 写入 `proactive_actions.external_message_id`，状态置 `delivered`。
- **Step 6**：失败分支——Feishu 429/超时仅重发（不重生成、不重裁决），重试耗尽 → failed 终态并记 outcome。

## 7. API / Interface Design

```text
Interface: delivery.send_proactive（已交付，FEISHU-005）
Input: internal_user_id, text, idempotency_key
Output: SendResult{ external_message_id, ... }
Responsibility: 主动消息目标解析 + Channel 投递，返回外部消息 id
```

```text
Interface: channel_identity_service.resolve_recipient
Input: internal_user_id, channel
Output: RecipientRef{ external_id }
Responsibility: internal_user_id → 渠道外部 id 映射
```

> 不新增 `/api/autonomy/*` 端点；全部经内部 Application Service + Background Worker 完成。

## 8. Integration Points

- **Agent Runtime**：`proactive_executor`（执行器）在统一执行链路中补投递，不绕过。
- **Channel 抽象**：依赖 `app.channels.base` 的 `OutboundMessage`/`ChannelAdapter`/`SendResult`，**不 import** `app.channels.feishu`。
- **Feishu Delivery**：`delivery.send_proactive`（FEISHU-005 已交付能力，当前无生产调用方，本任务成为首个生产调用方）。
- **Conversation Service**：`save_proactive_turn` 落库主动消息 turn。
- **Memory DB**：只经 Application/Service 边界读写，Autonomy 不直接操作。

## 9. Implementation Plan

- **Step 1**：`ProactiveActionRow` 增 `external_message_id` 列（nullable）+ 迁移。
- **Step 2**：`proactive_executor` 生成/落库后调用 `delivery.send_proactive`，回填 `external_message_id`，重定义 `delivered` 语义。
- **Step 3**：生成/发送两阶段拆分，Channel 失败仅重发不重生成；补 `_recheck` 用户已回来分支。
- **Step 4**：trace 补齐 `external_message_id` + `channel` 字段关联。

## 10. Acceptance Criteria

**功能验收：**

- 给定 approved action，当执行，那么文本生成后真实调用 `send_proactive` 且成功回填 `external_message_id`。
- 给定 Feishu 429/超时，那么仅重发、不重新生成、不重新裁决。

**架构验收：**

- Autonomy 不 import `app.channels.feishu`，只依赖 `app.channels.base`。
- 生成与发送两阶段解耦，`internal_message_id` 与 `external_message_id` 不混用。

**边界验收：**

- 给定发送前用户已回来，那么 `_recheck` 后 discarded，不投递。
- 重试耗尽 → failed 终态，不无限重试；`dedupe_key` 作为 `idempotency_key` 传递抑制双发。

## 11. Testing Plan

- **Unit Test**：发送调用与 `external_message_id` 回填逻辑；`_fail_for_retry` 与 `_recheck` 分支。
- **Integration Test**：成功路径（生成→落库→发送→回填）；Feishu 429 失败重发路径；竞态路径（发送前用户回来）。
- **Manual Test**：真实 Feishu 账号验证主动消息真实送达；连续触发验证不双发；断开网络验证重试与终态。
