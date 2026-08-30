# M7 World Context Builder

> 目标：世界信息**有选择地**进入角色。原则：World 是状态系统，Prompt 只收切片——不全部注入。

## 1. 装配流程与挂载位置

```text
chat_pipeline（H1，context_builder 之前 +1 行）：
    world_ctx = world_engine.build_context(user_id, session_id, trace=trace)
        ├─ ensure_world(user_id)                     幂等；失败 → world_ctx=None（降级）
        ├─ TimeContext（TimeProvider）
        ├─ LocationContext（当前位点 + available_actions）
        ├─ environment / objects / events（仓储按选择器条件查）
        ├─ WorldContextSelector.select(world, hints) → 有界 WorldContext
        └─ trace.record("world_context", …)          观测口径接入 V7.8（step 注册表增名）
answer_chain / PromptBuilder（H2/H3）：
    PromptBuilder.build(..., world_ctx=None)         非空 → 追加【世界】段；None → 字节不变
```

- build_context 的 DB 读是热路径读（与 scene_service.load 同性质），但**每 turn 仅一次**、索引直查、无 LLM；失败即 None 降级。
- 解释与迁移（写路径）不在这里——在第 8 步 post_process（见 §5）。

## 2. WorldContextSelector（选择规则）

输入：World 装配结果 + hints（当前用户消息、intent、scene_intent——只读现成变量）。输出：有界 WorldContext。

| 分区 | 选择规则 | 预算（字符） |
|---|---|---|
| time | 恒选 | ~60 |
| location | 恒选：current + path + available_actions | ~120 |
| events | due 今日 / active / completed ≤1 轮前；importance=high 优先；≤3 条 | ~200 |
| objects | 同 location 的 active 物品；近期被引用（解释器 last_action_at 邻域）优先；≤3 条 | ~150 |
| environment | 有值才选；全部默认则省略 | ~80 |
| notes | 解释器/校验备注（"西瓜在厨房"） | ~60 |

- 总预算 `world_context_char_budget`（默认 600）：超限按 priority（time > location > events > objects > environment > notes）从低优先级整条丢弃，不截半句。
- **排除规则**（"10 公里外的天气"问题的同族）：非当前地点的物品不进 nearby（只以 note 提及位置线索）；已完成且低重要度的事件不进；furniture 类静止物品不进（除非被引用）。
- 确定性纯函数：selector 不做 LLM 调用、不做 IO——口径可表驱动测试。

## 3. Prompt 渲染格式（answer 段）

```text
【当前世界】
现在是周日晚上 22:40（深夜）。你在家里·厨房。
外面在下雨，18℃。
冰箱里有半个切开的西瓜（0.4），今天下午刚放回去。
明天上午用户有一场重要面试。
```

- 一个 section（【当前世界】），追加在 tail 区域（scene/mode 段附近），复用 _literal 转义惯例。
- 渲染由 `render_world_section(world_ctx) -> str | None` 纯函数完成：**None → 不追加该段 → golden 字节不变**。
- world_ctx 为 None（未初始化/禁用/降级）与空切片同样输出 None——单一不变量。

## 4. 不变量（机器可证）

1. **golden 不变量**：无世界数据 / world_enabled=false 时，全部既有 golden prompt 字节不变。
2. **预算不变量**：渲染后的世界段 ≤ `world_context_char_budget`。
3. **幂等不变量**：同一世界状态 + 同一 hints → 渲染字节确定（时间字段除外，测试以注入 TimeProvider 冻结）。
4. **零写回不变量**：build_context 全程只读世界与只读既有对象；测试断言无 character/relationship/emotion/memories 写。

## 5. 与解释器的职责分工

```text
WorldContextBuilder（读，热路径）：世界现状 → 有界切片 → prompt
World Update Interpreter（写，第 8 步）：用户消息 + 世界现状 → 状态迁移（object/location/event/environment）
```

- 两者共享仓储与资产词表，但互不调用；解释器的输出（迁移 + notes）在**下一轮**装配时自然可见。
- notes 传递：第 8 步把本 turn 的解释备注写入 world.notes 短期字段（世界行，TTL 一轮语义），下一轮选择器带走后清除——实现"这轮说、下轮知道"的最小闭环。

## 6. 边界

- 不为 world_ctx 增加独立 LLM 摘要链（渲染是模板拼接）；不把世界 JSON 直接 dump 进 prompt。
- 不实现按用户手动开关世界段的前端 UI（debug API 可查，前端按既有边界跳过）。
- 世界段不参与 token 预算的既有裁剪函数（_fit_variable_parts）——自带独立预算，互不干扰。
