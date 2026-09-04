# State Update

## 1. 背景

V2 的 `state_update_chain` 全部状态变化交给 LLM 决策（StateUpdateDecision）。对场景状态而言，其中一半变化是**确定性的**，不需要也不应该经过 LLM。

## 2. 原则

> 确定性状态变化由代码处理，语义判断才交给 LLM。

## 3. 分工

| 变化 | 执行者 | 时机 |
|---|---|---|
| interrupt → cancel pending | 代码（Resolver） | 回答前 |
| correct → 激活 pending | 代码（Resolver） | 回答前 |
| pending 过期 | 代码（Resolver） | 回答前 |
| location / current_activity / current_action / 新 pending / 完成 pending | LLM（Updater） | 回答后（后台） |

## 4. Updater 设计

- 输入：上一轮 SceneState + SceneIntent + Resolver 迁移结果 + 用户消息 + AI 回复。
- 输出：`SceneActionDecision`（结构化输出，见下），**不是**完整新状态。
- 代码做白名单合并：只接受 Decision 中显式 set/clear 的字段，未知字段忽略；每字段 ≤ 50 字超长截断。

```python
class SceneActionDecision(BaseModel):
    location: str | None = None
    current_activity: str | None = None
    current_action: str | None = None
    new_pending_action: str | None = None      # 仅限本轮 SceneIntent=request_action 时由代码传入；Updater 不得自行创造
    pending_action_done: bool = False
    pending_action_cancel: bool = False
```

**Updater 边界（V3 核心原则，见 architecture.md 3.1）**：Updater 只能识别"刚刚发生了什么"，不能创造"接下来要发生什么"。`new_pending_action` 仅在本轮 SceneIntent=request_action 时由 Resolver 传入确认，Updater 自行输出的 new_pending_action 一律丢弃并记 trace warning。

## 5. 防 LLM 改错状态

1. Decision 只能 set/clear 白名单字段，无自由写。
2. Resolver 的确定性结果（如本轮已 cancel）优先于 LLM 输出。
3. Updater 失败/输出非法 → 状态保持上一轮原样（宁可保守），trace 记 error。
4. scene_mood 仅内存传递，不落库，错误不影响后续轮次。

## 6. 流程

```text
User Message + Previous SceneState + AI Response
        ↓ SceneActionDecision（LLM, 后台并行）
        ↓ 代码白名单合并 + 截断
        ↓ scene_state_repository 写回（upsert）
New Scene State
```

## 7. 验收标准

- 确定性迁移有纯代码单测（不调 LLM）。
- LLM 输出注入非法/超长字段时被拦截。
- Updater 异常不影响已产出的回答（沿用 V2 后处理容错模式）。
