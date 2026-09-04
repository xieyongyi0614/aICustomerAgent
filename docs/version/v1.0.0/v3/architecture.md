# V3 Architecture

## 1. 背景

V2 管道为线性：`context_builder → (role_router ∥ turn_analyzer) → answer_chain → 后台 state_update/memory/summary`。它解决了"角色像不像"，但没有解决"剧情是否连贯"。

## 2. 问题

- 无场景状态：AI 不知道地点/当前活动/正在做的动作。
- 无行为连续性：说出口的动作（"我去切西瓜"）没有被跟踪。
- 状态更新全靠 LLM，无确定性路径，用户纠正无法优先生效。

## 3. 目标

在**不重构**现有管道的前提下，插入场景状态层：

```text
User Message
      │
      ▼
context_builder（V2，复用）+ scene_state_loader（V3 新增，读上一轮 SceneState）
      │
      ▼
role_router (V2) ∥ scene_intent_router (V3)     ← asyncio.gather 并行
      │
      ▼
scene_action_resolver（V3 新增，纯代码）
  根据 SceneIntent + PendingAction 做确定性状态迁移
      │
      ▼
answer_chain（V2）← PromptBuilder 注入 scene 段 + rhythm 段
      │
      ▼
AI Response（SSE 流式，复用 V2）
      │
      ▼
scene_state_updater（V3 后台，与 V2 的 state_update/memory/summary 并行）
  LLM 只识别"刚刚发生了什么" → 白名单合并 → 写库
```

## 3.1 V3 核心原则（必须写进实现）

> **Resolver 决定"应该怎么走"，Updater 只负责"记录刚刚发生了什么"。**

- Resolver（纯代码）：根据 SceneIntent + PendingAction 做确定性状态迁移，是唯一能决定剧情走向的状态变更者。
- Updater（LLM，后台）：只能**识别已经发生的事情**（如 AI 回复"我把西瓜递给你" → `pending_action_done=true, current_action="递西瓜"`），**不能创造接下来要发生的事情**（禁止 Updater 自行输出 `new_pending_action` 来脑补后续剧情；new_pending_action 只能来自 SceneIntent=request_action 的用户明确请求）。
- 这条边界防止 LLM 绕过 Resolver，是 Resolver 设计成立的根基。

## 4. Runnable vs LangGraph

| 维度 | LangChain Runnable（现状） | LangGraph |
|---|---|---|
| 流程形态 | 线性 + gather 并行，够用 | 图，含条件边/循环 |
| SSE 流式 | 已验证 | 需重新接入 |
| trace 集成 | trace_collector 成熟 | 需适配 |
| 测试 | FakeLLM 体系成熟 | 重写编排测试 |
| 收益 | — | 可视化、断点恢复（当前不需要） |

**结论：本阶段继续 Runnable。** 触发迁移条件：出现需要多轮循环决策的场景推进、需要图级 checkpoint 恢复、或有条件分支循环。

## 5. 边界情况

- SceneIntent 路由失败 → 降级 `chat`，不影响回答（同 V2 降级模式）。
- scene_state 表读取失败 → 使用默认空 SceneState，不阻塞回答。
- Updater 失败 → 状态停留在上一轮（宁可保守，不猜测），记录 trace error。

## 6. 验收标准

- 现有 V2 全部测试通过，无回归。
- trace 中可见 `scene_intent`、`scene_resolver`、`scene_update` 三个新 step。
- 七大 Case（见 testing.md）全部通过。
