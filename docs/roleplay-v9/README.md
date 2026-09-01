# Roleplay V9：Action Capability System（行动能力系统）

> 状态：**设计完成，待实现**。任务入口 tasks.md。前置：V1~V8 全部完成（V8.5 关系演化可并行，见 relationship-impact.md §6）。
> 设计原则：**Action ≠ Response**——Response 是语言输出，Action 是改变状态；角色永远不直接调用工具，必须走 `Intent → Decision → Action Plan → Capability → Result`；**Tool 是能力，不是逻辑**——Character Brain 决定做什么，Capability 只负责执行。

## 1. V9 解决什么问题

V8 为止，角色已经能思考、规划、表达、模拟行动，但**不能真正执行行动**。用户说"明天提醒我开会"，角色回答"好的，我会提醒你"——而实际上没有任何 Reminder / Calendar / Event / Notification 被创建。承诺从未落地。

```text
V8 为止：
用户消息 ──→ Character Runtime ──→ Response（行动只停留在 *动作描写* 与口头承诺）

V9 之后：
用户消息 ──→ Action Intent Detector（确定性检出）
                  ↓
             Action Planner（闸门 + 计划装配，纯函数）
                  ↓
             Capability Runtime（Registry + Executor，插件化）
                  ↓
             ActionResult ──→ World / Memory / Relationship / 行动上下文
                  ↓
             Response（后续轮次基于真实行动事实表达）
```

V9 之后必须能回答：

1. **角色是否真的做了？** 每次行动一条 ActionRecord，六态生命周期可审计。
2. **行动改变了什么？** ActionResult 携带效果清单（世界/记忆/关系），逐项落库。
3. **行动失败了怎么办？** 重试退避、失败留痕、下一轮行动上下文可见、评估规则兜底。
4. **角色知道自己的行动吗？** 行动上下文段（下轮 prompt）+ 自治事实包（action_facts）。
5. **行动是否被恰当宣称？** 回复宣称与 ActionRecord 矛盾时由评估规则检出（action_overclaim）。

## 2. 硬边界（V9 明确不做）

- **不实现真实第三方 API**：天气 / 搜索 / 日历 / 推送全部提供 manual 与 simulated 两种实现（沿用 V8 TimeProvider 模式），接口为未来插件预留；Reminder 的存储后端就是 V8 WorldEvent，不新建平行日程系统。
- **不引入 Tool Calling / Function Calling**：LLM 永远拿不到工具接口——answer_chain 等生成链零修改；能力只被后置的确定性编排器调用。行动检出用确定性词表规则，LLM 辅助链仅留接口、默认关（V8 interpreter 同款成本纪律）。
- **不做机器人控制 / 浏览器操控 / 复杂 Agent 框架**：无 MQ、无 DAG 编排、无多 Agent；执行环境 = 单进程 lifespan + per-user 写锁（V7 outbox 模式推广）。
- **不替换现有 Runtime**：全部挂载点是加法；V7 `ProactiveAction`（type 锁定 send_message）**不迁移**，V9 ActionRecord 是并行的通用行动记录；V8 interpreter（话语→世界的被动解释）原样保留，与 V9 主动执行器分工见 world-integration.md §5。
- **行动默认关**：`action_enabled=false` 出厂——行动有外部副作用，检出基于文本无法靠"空世界"兜底，必须开关兜底；灰度路径：debug 端点验证 → 真实模型人工回归 → 默认开。
- **本阶段只输出设计**：不写实现代码（任务在 tasks.md），不实现 HomeControl / Browser / Robot（仅在插件化约定中预留）。

## 3. 核心设计一览

| 模块 | 职责 | 核心载体 | 落点 |
|---|---|---|---|
| M1 Action Domain Model | 行动域模型与生命周期 | ActionIntent / ActionPlan / ActionStep / ActionResult / ActionRecord / ActionStatus 六态 | `app/models/action.py`（Domain） |
| M2 Action Planner | 检出 / 闸门 / 计划装配 | ActionIntentDetector + 六闸门纯函数 + ACTION_CAPABILITY_MAP | `app/services/action/` |
| M3 Capability System | 能力抽象与注册 | Capability 协议 / CapabilityRegistry / CapabilitySpec | `app/services/action/capabilities/` |
| M4 Execution Engine | 执行编排与容错 | ActionEngine / CapabilityExecutor（超时/重试/幂等） | `app/application/action_engine.py` |
| M5 Result Integration | 结果整合四通道 | World Update → Memory Decision → Relationship Impact → Response | post_process 第 9 步 |
| M6 World Integration | 行动 ↔ V8 双向 | 行动写 world_engine 既有 API；due 提醒 → 自治事实 | world_engine（零修改消费） |
| M7 Memory Integration | 行动记忆政策 | Action Memory Policy 边界表 + 候选投递 | `app/services/action/memory_bridge.py` |
| M8 Relationship Impact | 行动 → 关系信号 | RelationshipEvent 投递 + 三层钳制（默认关） | `app/services/action/relationship_bridge.py` |
| M9 Autonomy Integration | 行动 ↔ V7 双向 | PolicySnapshot.action_facts（只读）+ due_action 触发器 | V7 policy 增可选参数 |
| M10 Evaluation Integration | 行动质量审计 | action 评估维度 + 3 条规则（overclaim 等） | evaluation_rules 扩展 |
| M11 Persistence | 行动存储 | action_records 表 + action_repository | 迁移 0018 |
| M12 Context & API | 行动上下文段 + 调试端点 | action_ctx 可选 prompt 参数 + /debug/actions | builder / api/v1 |

一条纪律贯穿全程：**行动是旁路——检出不确定不执行（宁缺毋滥），执行失败只降级（回复照常），结果不直接变回复（走四通道），开关关闭时全链路字节回到 V8.5 行为。**

## 4. 与既有系统的边界（最容易混淆的四对）

| 概念 | 域 | 归属 | 例子 |
|---|---|---|---|
| Intention（V6） | 会话 | 言语行为意图（说什么）：comfort / suggest_rest… | "安慰用户" |
| ActionIntent（V9） | 用户（跨会话） | 执行行动意图（做什么）：create_reminder / create_object… | "给用户设提醒" |
| ProactiveAction（V7） | 用户（跨会话） | 主动发消息队列（type 锁 send_message） | "主动问一句最近怎么样" |
| WorldEvent（V8） | 用户（跨会话） | 世界事实（会到期、会完结） | "明天面试" scheduled → active |
| PendingAction（V3） | 会话 | 叙事义务（场景连续性，纯文本） | "用户刚让我拿水，动作进行中" |

- 行动执行后产生的事实**落入既有宿主**：提醒 = WorldEvent(type=reminder)、采购 = WorldObject、显式记忆 = memories 表——V9 不新增事实存储，只新增"执行记录"存储（action_records）。
- ActionRecord 记录"执行审计"（做过什么、成败如何），WorldEvent 记录"事实存续"（什么时候到期、是否完结）——两者的生命周期分工见 world-integration.md §4。

## 5. 文档导航

- [architecture.md](architecture.md) — 总体架构、挂载点清单、失败契约、开关矩阵（先读这篇）
- [action-model.md](action-model.md) — M1：六态生命周期、ActionIntent/Plan/Step/Result/Record 模型
- [planner.md](planner.md) — M2：确定性检出、六闸门、计划装配、与 V6 Intention 的边界
- [capability-system.md](capability-system.md) — M3：能力协议、Registry、MVP 能力清单、插件化约定
- [execution-engine.md](execution-engine.md) — M4：ActionEngine 编排、超时/重试/幂等、失败分类
- [tool-integration.md](tool-integration.md) — M5+M10：结果整合管线、回复时序契约、行动评估规则
- [world-integration.md](world-integration.md) — M6：行动→世界写通道映射、与 V8 interpreter 的分工
- [memory-policy.md](memory-policy.md) — M7：哪些行动沉淀记忆的边界表与投递路径
- [relationship-impact.md](relationship-impact.md) — M8：行动→关系信号、钳制、V8.5 兼容
- [autonomy-integration.md](autonomy-integration.md) — M9：action_facts、due_action 触发器、自治产行动预留
- [testing.md](testing.md) — tests/v9/ 七套件 + 性能护栏 + 回归底线
- [tasks.md](tasks.md) — 任务注册表（V9-001 ~ 010）

## 6. 关键架构事实

```text
1. 全部挂载点是加法：post_process 追加第 9 步（STEP_HANDLERS 官方扩展点）、prompt 增可选
   action_ctx 参数（V8 world_ctx 同构三连）、PolicySnapshot 增 action_facts（默认空）。
   action_enabled=false 时全链路逐字节回到 V8.5 行为，golden 字节不变是机器可证底线。
2. 检出与决策全部确定性：ActionIntentDetector 是词表+参数抽取的纯函数（零新增 LLM 调用），
   六闸门是纯函数；LLM 只在既有生成链里被调用，V9 不给任何链新增工具。
3. 执行在后台：run_action_planning 在 post_process（per-user 写锁内），不阻塞回答流；
   回复使用进行时承诺（"我去设个提醒"），完成时宣称（"已经设好了"）只能出现在行动
   成功之后的轮次——由行动上下文段驱动，评估规则 action_overclaim 兜底。
4. 外部效果全部先落 V8：提醒=WorldEvent(due_at)、采购=WorldObject、取消=cancel_events；
   V9 是世界的第一个主动执行者（V8 interpreter 是被动解释者），世界零修改。
5. 行动记忆走既有通道：候选经 memory_policy R1~R8 校验后由 memory_repository 落库，
   source 只用 user_stated（显式委托）/ user_derived（推导演生），不用 ai_inferred（R1 丢弃）。
6. 一切阈值与开关进 settings action_* 组（19 项，含 autonomy_action_* 2 项）；迁移自 0018 起；全量既有测试
   零回归（action_enabled=false 下逐字节一致）是每个 Task 的底线。
```
