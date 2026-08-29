# V6.5 Architecture

## 1. 当前真实架构（依据代码，chat_pipeline 为准）

```text
POST /api/v1/chat/message
  → application/chat_pipeline.run_chat_pipeline          ★ 前台关键路径
      ├─ context_builder.build（states/memory/summary/history/goals）
      ├─ scene_service.load
      ├─ goal_service.select（确定性）
      ├─ asyncio.gather 4 链：role_router ‖ turn_analysis ‖ scene_intent ‖ intention
      ├─ scene_service.resolve
      ├─ intention_policy.enforce → ValidatedIntention
      ├─ PromptBuilder.build → answer_chain.astream（流式）
      ├─ conversation_service.save_turn
      └─ schedule_post_process
  → application/post_process.py                          ★ 后台 5 步（STEP_HANDLERS）
      scene_update ‖ state_update ‖ goal_review ‖ summary ‖ memory_extract
```

## 2. V6.5 接入点（不新增 God Object，走既有缝）

```text
前台（chat_pipeline，三处改动）：
  ① context_builder.build → 顺带读 conversations.mode / mode_entered_at（已有会话行）
  ② gather 后：mode_service.stabilize(...)      纯函数：confirmed × router 候选 → 生效 mode
  ③ intention_policy.enforce 之后：
       behavior_engine.resolve(...)             纯函数：intention + state + scene + mode
                                                → BehaviorDirective（strategy/budget/habits/activity）
  ④ PromptBuilder.build(behavior_ctx=...)       渲染【表现方式】段 + RHYTHM 动作行替换
                                                + 【活动延续】段
  ⑤ save_turn 同事务写回 mode（stabilize 判定切换时）

后台：零新增步骤（mode 写回随 save_turn 事务；V6.5 无后台需求）
```

```text
                         ┌────────────────────────────────────────────┐
 State(scene/emotion/    │            Behavior Engine（纯函数）         │
 rel/goal)+Mode+Scene ──►│  strategy = MAP[intention] + 修饰规则(白名单)  │
 ValidatedIntention ────►│  budget   = 预算表(mode×stage×mood×策略×活动)  │
                         │  habits   = domain 适用 + priority ≤2 条      │
                         │  activity = classify(scene_state)            │
                         └──────────────┬─────────────────────────────┘
                                        ▼
                    PromptBuilder【表现方式】+【活动延续】+ RHYTHM 收口
                                        ▼
                              answer_chain（LLM，不变）
                                        ▼
                    save_turn（mode 写回）→ post_process（不变）
```

## 3. 新增代码模块（全部纯函数/纯数据，零新增 LLM 链）

| 模块 | 职责 | 形态 |
|---|---|---|
| `app/models/behavior_strategy.py` | BehaviorStrategyType 12 值 / BehaviorStrategy / ActionBudget / BehaviorPolicy / HabitRule / BehaviorDirective / ActivityPresence | Pydantic 模型 |
| `app/character/asuna/behavior_policy.py` | BEHAVIOR_POLICY（stage×mood 参数表）+ STRATEGY_INSTRUCTIONS | 角色资产常量 |
| `app/character/asuna/habits.py` | HABIT_LIST（7 条）+ 适用域表 | 角色资产常量 |
| `app/services/behavior_engine.py` | resolve：strategy 修饰 / budget 计算 / habit 匹配 / activity 分类 | 纯函数服务 |
| `app/services/mode_service.py` | stabilize：迟滞稳定器 5 规则 | 纯函数服务 |
| `app/prompts/behavior.py` | build_behavior_sections 渲染 | 渲染模块 |
| `migrations/versions/0010_conversation_mode.py` | conversations +mode +mode_entered_at | 迁移 |

修改的现有文件：`chat_pipeline.py`（②③）、`context_builder.py`（①）、`conversation_service.py`（⑤）、`prompts/builder.py`（④）、`models/conversation.py`（mode 字段）、`core/db.py`（Conversation ORM）。

## 4. 与既有 State 的边界

| 系统 | 回答的问题 | V6.5 关系 |
|---|---|---|
| V3 Scene | 在做什么/待完成动作 | Activity 复用其字段只读；pending 收束 Strategy；directive 优先于表现层 |
| V4 Memory | 过去发生了什么 | 只读（无新交互）；动态 habit 养成是 P2 且走审核 |
| V5 Emotion | 现在感觉怎样 | mood/intensity 是 Strategy 修饰与 Budget 查表输入；不回写 |
| V5 Relationship | 和用户什么关系 | stage 是 policy 分档/Budget/接触等级取值维度；tension>0.5 触发 reserved_distance |
| V6 Goal/Intention | 想要什么/做什么 | intention 是 Strategy 唯一映射源；V6.5 不改 goal/selection 任何逻辑 |
| V7 Autonomy | 什么时候主动行动 | 不相交；V7 主动消息文本可复用【表现方式】渲染（V7 接入，非本期） |

禁止事项：
- Behavior 层不得修改 Intention/Goal/Scene/Emotion 任何状态（单向只读）。
- Budget/Strategy 不做输出侧拦截（流式架构决定，action-budget.md §2）。
- Mode 不引入第二套基调枚举（conversation-mode.md §1.2）。

## 5. 关键时序（SSE 零退化论证）

- gather 保持 4 链并行，V6.5 不加链。
- 新增前台计算全部纯函数：stabilize（微秒）+ behavior_engine.resolve（查表 3 次 + 一次列表过滤，无 IO）。gather 后串行新增 < 1ms，wall time 无感。
- prompt 段净增 ~150 字（response-controller.md §5），计入 fixed_chars，history 滑窗吸收。
- DB 增量：mode 读取 0 次（ensure_conversation 已取行）；写回 0~1 次 UPDATE 随 save_turn 同事务。

## 6. 失败降级（行为层永不为空）

| 失败 | 降级 |
|---|---|
| intention 链失败/非法（已有） | ValidatedIntention 降级 continue_topic → Strategy=natural_continuation，V2 行为段 fallback 可用 |
| behavior_engine.resolve 异常 | BehaviorDirective(degraded) → V2 行为段 + 默认 Budget，answer 不受阻 |
| mode 稳定器输入缺失（mode 列 NULL/读失败） | 生效=default（等价现网），stabilize 走 R5 |
| policy/habit 资产加载异常 | 启动期即失败（import 时校验），不进入运行时 |
| conversations.mode 写回失败 | save_turn 整体异常按现有落库失败路径处理；模式退回上一确认值，下轮重评 |
