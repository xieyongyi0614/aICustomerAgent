# Activity State

## 1. 关键决策：复用 V3，不新建存储

V3 SceneState 已经完整回答了 Activity 的存储与更新问题：

| 问题 | 结论 |
|---|---|
| Activity 保存在哪里？ | `scene_state` 表的 `current_activity` / `current_action` 列（V3 已有）；为空即 idle |
| 什么时候更新？ | 每轮 post_process 后台的 scene_update_chain（V3 已有） |
| 谁负责更新？ | scene_update_chain（LLM 出 SceneActionDecision）→ scene_service.update_and_persist（V3 已有） |
| 如何影响 Response？ | **V6.5 新增**：表现层三个影响（见 §3） |

V6.5 不建 `character_activities` 之类的表，不做第二个活动系统。V3 缺的不是存储，而是**活动对回复表现的约束**。

## 2. 现状缺口

`build_scene_sections` 已把 `current_action` 注入【当前场景】段（「正在做：切西瓜」），但只是**信息罗列**，没有表达约束。实测缺口：

```text
用户：给我拿西瓜      → 角色切西瓜（V3 pending_action 正常）
用户：天气怎么样      → 角色凭空切换成天气播报员，手上的西瓜消失了
```

V3 的 scene_intent=question 路径解决了「先完成/继续动作再回应」的**流程**问题，但回复文本里「边做事边回答」的**表现**问题无人负责——这正是 V6.5 Activity 表现层的范围。

## 3. V6.5 新增：表现层三件事

### 3.1 活动连续性指令（渲染层）

`current_activity` 非空（非 idle）且本轮 scene_intent ∈ {question, chat, emotional}（用户没在推进场景）时，渲染：

```text
【活动延续】
你正在做的事：切西瓜。回答这轮话题时自然带着这个状态（手上动作、注意力分配），
不要凭空停下或无视它；除非用户话题直接涉及当前活动。
```

- 注入位置：tail 的场景段之后（与 scene_ctx 同生命周期），由 Response Style Controller 渲染（response-controller.md §4）。
- idle 或用户正在推进场景（request_action/continue_scene/correct_scene/interrupt）时不渲染——后者场景段已有 directive 接管。

### 3.2 Activity → Action Budget 修饰

`current_activity` 非空时 `max_action_desc` 减 1（action-budget.md §4 步骤 5）：当前活动本身占用动作，回复再堆动作描写就是双重旁白。这是「切西瓜时回复里没有动作」的量化表达。

### 3.3 Activity → Strategy 修饰

存在 pending_action 时 Strategy 收束为 `natural_continuation`（behavior-strategy.md §3.2 规则 5，场景叙事优先于表现花样）。仅 pending_action 触发，`current_activity` 单独存在时不改策略——「一边吃着东西一边正常聊天」是合理常态。

## 4. Activity 语义分层（与 V3 字段的对应）

```text
idle                activity/action/pending 全空          → 无表现层注入
ambient_activity    current_activity 有值、无 pending     → 延续指令 + Budget −1
engaged_action      current_action 有值（正在执行）        → 延续指令 + Budget −1
pending_obligation  pending_action.status == pending      → V3 directive 接管 + Strategy 收束
```

分层映射是纯函数（`classify_activity(scene_state)`），输入为 V3 已有字段，输出为 `ActivityPresence` 枚举，供渲染层与 Budget 查表。不新增任何持久化字段。

## 5. 明确不做

- 不做世界模拟/时间推进/独立活动调度（V7 action-queue 之外的活动系统属 V8+，V7 的主动行为也不依赖它）。
- 不修改 scene_update_chain 的判定逻辑（V3 已验收）。
- 不把 activity 写进 character_state 或新表——活动属于场景，不属于角色内在状态。
- scene_mood 已确认为废弃字段（不落库、无写入方），V6.5 不复活它，活动氛围由 V5 mood 与 scene 段共同覆盖。

## 6. 测试要点

- 切西瓜后问天气：FakeLLM 断言 prompt 含【活动延续】段且 Budget 减 1（testing.md §Activity）。
- idle 会话无延续段、无 Budget 抖动。
- pending 场景：directive 优先、无双重约束（延续段不与 directive 同时出现）。
