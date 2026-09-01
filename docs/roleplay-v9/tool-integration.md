# V9 Tool Result Integration（结果整合与评估）

> 工具返回**不能直接变回复**。本篇定义 CapabilityResult 的五段整合管线、回复时序契约、行动上下文段，以及 Action Evaluation（M10）——检测行动是否合理、是否成功、是否需要修正。

## 1. 五段整合管线

```text
CapabilityResult（能力产物：world_event_id / memory_id / 查询切片…）
    ↓
① World Update        效果落世界（create_reminder → WorldEvent 已由能力写入；
                       查询类 → 只读不写世界）
    ↓
② Memory Decision     Action Memory Policy 裁决：本次行动是否值得沉淀（memory-policy.md）
    ↓
③ Relationship Impact 行动成败 → 关系信号（relationship-impact.md，默认关）
    ↓
④ Action Note         行动效果摘要（≤200 字）→ 下轮上下文 + 自治事实包
    ↓
⑤ Response            由既有生成链在**后续轮次**基于真实行动事实表达
```

整合在 `integrate_result`（execution-engine.md §1）内顺序执行；单通道失败只 log，不影响其他通道（效果清单 ActionEffect 逐条记录实况——成功了几条算几条，补录语义，无分布式事务）。

## 2. 效果 → 宿主映射（①④ 详表）

| CapabilityResult | ① World Update | ④ Action Note |
|---|---|---|
| reminder.create → WorldEvent | 能力内已写（create_event），此处只登记 effect[world] | "已设提醒：{title}，{due 人类可读}" |
| reminder.cancel → cancelled 事件数 | 能力内已写（cancel_events_by_type），登记 effect | "已取消提醒：{target}" |
| memory.save → memory_id | 无世界效果 | "已记住：{fact ≤40 字}" |
| world_action.create/move/use → WorldObject | 能力内已写，登记 effect | "{object} 现在{state}@{location}" |
| environment_query → 切片 | 无写（只读） | "当前{天气}{温度}°C"（simulated 注明） |
| search / notification → unavailable | 无 | "该能力尚未接入"（info） |

- ① 的职责边界：**能力的副作用在能力内写**（reminder 能力调 world_engine.create_event），整合层只负责登记 effect + 校验宿主存在（防幻觉登记）——世界写通道唯一（world_engine），V9 无第二条写路径。
- 查询类行动的世界读结果不进本轮回复（见 §3），但**进世界 notes**（V8 `World.notes` 既有有界机制，"本轮说、下轮知道"语义扩展到行动）。

## 3. 回复时序契约（⑤ 的纪律）

```text
T0 轮  用户："明天提醒我开会"
       检出 confident → 回复生成时对行动一无所知
       → 回复只能说进行时承诺："好，我去设个提醒。"          ✅ 允许
       → 不得宣称完成："已经设好了。"                       ❌ 此时行动尚未执行
T0+1 轮 行动上下文段："已设提醒：开会，明天 08:00（scheduled）"
       → 完成时宣称此刻起才有事实依据："提醒设好了，明早八点我叫你。"
```

- 契约成立机制：检出**不进本轮 prompt**（planner.md §4），执行在 post_process（回复之后），行动事实**下轮才可见**——LLM 想虚假宣称也没有事实输入，契约由架构保证而非 prompt 恳求。
- 失败场景：T0 轮回复做了进行时承诺，行动 failed → T0+1 行动上下文段标注"上次设置提醒未成功（原因）"→ 下一轮自然补救（追问参数/道歉），或自治触发器带动主动补救（autonomy-integration.md §3）。
- 评估兜底：完成时宣称 + 无 succeeded 记录 → action_overclaim（§5）。

## 4. 行动上下文段（action_ctx）

- 装配：`app/services/action/context.py::build_action_context(user_id, session_id) -> ActionContext | None`，挂载于 chat_pipeline 世界上下文之后（H-A3 与 world_ctx 同构三连：builder 装配 → PromptBuilder 可选参数 → answer_chain 透传）。
- 渲染 `render_action_section(ctx, budget=action_context_char_budget)` 纯函数，【行动】段内容（优先级序，预算内截断打标）：

```text
【行动】
进行中：买牛奶（create_object，重试中，第 2 次）
已设提醒：开会 · 明天 08:00（scheduled）
上次失败：查"今天新闻"未成功——能力未接入
```

- 选择规则：非终态行动全部进入（≤3 条）；最近 succeeded/failed 按 updated_at 倒序取 ≤2 条；cancelled（闸门否决）**不进** prompt（对角色不可见，仅审计可见——否则 LLM 会向用户解释内部闸门）。
- 不变量：`action_ctx=None`（无行动记录或开关关）时 prompt 字节与 V8.5 完全一致；段独立预算，不参与既有变量裁剪。

## 5. Action Evaluation（M10）

新增评估维度 `action`（V7.5 EvaluationDimension 扩值）+ 3 条规则（`app/services/evaluation_rules/action.py`），开关 `evaluation_action_enabled`（默认 true，随总闸 evaluation_enabled）。EvaluationContext 增 `action` 切片（H-A8，`_collect_action` 装配：本轮/近期 ActionRecord 摘要，失败降级 None——切片缺失时规则全部跳过，同 world 切片惯例）。

| 规则 | IssueCode | severity | 检测 |
|---|---|---|---|
| `ActionOverclaimRule` | `action_overclaim` | warning | 回复含完成时宣称（"已经设好/已提醒/已记住"模式表，角色资产）但本轮+近期无对应 succeeded ActionRecord（或行动 failed/cancelled）——时序契约的审计兜底 |
| `ActionUnreportedFailureRule` | `action_failed_unreported` | info | 存在近期 failed 且**未补救**（无后续 create/cancel 同型行动）的重要委托行动，而本轮对话触及同主题——提示未闭环（不判回复错误） |
| `ActionPlanMismatchRule` | `action_plan_mismatch` | warning | 检出的 intent 与回复语义明显无关（evidence 词不在回复窗口内）或闸门频繁否决同型意图（词表误报信号，gate_reason 统计阈值） |

- IssueCode 扩值 3 个进 `models/evaluation.py`（DEFAULT_SEVERITY / ISSUE_MESSAGES 同步）；维度权重进 `evaluation_overall_weights_json` 的 action 行（turn subject 权重表）。
- subjects：三条规则均 `("turn",)`——自治主动消息（send_message）暂无行动宣称面，预留 `proactive_action`。
- 语义分级：overclaim 是行为错误（warning）；unreported 是改进提示（info）；mismatch 双重身份（回复异常 + 词表质量信号）。
- 行动本身的"合理性"（该不该做）由 G1~G6 前置闸门判定，评估只做事后审计——**评估不改行动，行动不迎合评估**（与 V7.5 同源原则）。

## 6. 明确不做

- 不做"行动结果实时注入本轮回复"：时序契约的价值在于承诺与事实分离，实时注入会把行动成败耦合进回答流（阻塞 + 虚假宣称风险回归）。
- 不做行动结果 → 情绪直写：行动成败对情绪的影响只经既有 state_update 通道的自然演化（对话轮），V9 零直写。
- 不做用户通知推送通道：unavailable 占位 + 到期走 V7 主动消息，真实推送（WebSocket/Push）留待前端协议升级。
