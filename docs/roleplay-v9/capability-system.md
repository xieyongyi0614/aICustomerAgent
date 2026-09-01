# V9 Capability System（能力抽象与注册）

> 能力是角色与世界交互的**手脚**：能力知道"怎么做"，永远不知道"何时做、为何做"——决策权全部在 Planner。本篇定义能力协议、注册表、MVP 能力清单与插件化约定。

## 1. 三层职责分离（原则 3 的落点）

```text
错误：WeatherCapability 内部决定"下雨天要不要提醒带伞"      ← 工具僭越逻辑
正确：Planner 决定"query_environment"（何时/为何）
      WeatherCapability 只执行"读环境并返回结果"（怎么做）
```

| 层 | 拥有 | 永不拥有 |
|---|---|---|
| Planner | 触发时机、闸门、参数装配 | 执行细节、后端连接 |
| Capability | 执行细节、后端协议、结果归一 | 调度权、自主重试决策、回复生成 |
| Executor | 超时/重试/幂等/留痕 | 语义判断（什么算"值得做"） |

## 2. Capability 协议

```python
class ActionSchema(BaseModel):
    required: list[str]                       # 必需参数名
    optional: dict[str, str] = {}             # 可选参数名 → 类型说明
    validators: dict[str, Callable] = {}      # 参数级校验（范围/格式）

class Capability(Protocol):
    name: str                                 # reminder / memory / world_action / …
    description: str                          # ≤60 字（registry 描述与 debug 展示）
    actions: dict[str, ActionSchema]          # action → 参数 schema

    def validate(self, action: str, params: dict) -> list[str]      # 错误列表，空=合法
    async def execute(self, action: str, params: dict,
                      ctx: ExecutionContext) -> CapabilityResult    # 唯一执行入口
```

- `ExecutionContext`：user_id / character_id / record_id（审计回填用）/ now / settings——能力**只拿到执行上下文，拿不到对话与 prompt**（V4 privacy、V6"内部字段不进 Prompt"原则延伸：内部字段同样不进能力）。
- `execute` 必须幂等友好：同参数重复调用要么产生同效结果（查询类天然幂等），要么由 G4 去重闸拦截（创建类）。
- 能力实现**不得**直接写 Character 状态（情绪/关系/记忆直写禁止）；memory 能力是唯一记忆写入口，且只走既有 policy + 仓储通道（memory-policy.md §3）。

## 3. CapabilityRegistry

```python
class CapabilityRegistry:
    def register(self, capability: Capability) -> None        # 重名拒绝
    def get(self, name: str) -> Capability | None
    def has(self, name: str, action: str | None = None) -> bool
    def describe(self) -> list[dict]                          # debug 端点用
```

- 模块级单例，进程启动时注册内置能力；未注册能力在 G3 被否决（capability_unavailable）。
- 注册表不可变语义：运行期不增删（插件化 = 代码注册，不是运行时热插拔）——单进程 MVP 不需要动态发现，未来引入外部插件时再评估。

## 4. MVP 能力清单

全部为 manual/simulated 实现（硬边界：不接真实第三方 API）；落点 `app/services/action/capabilities/`。

| 能力 | 动作 | 后端（全部既有） | MVP 形态 |
|---|---|---|---|
| `reminder` | create / cancel | `world_engine.create_event(type=reminder/appointment, due_at)` / `cancel_events_by_type` | **真实现**：提醒 = WorldEvent(due_at)，到期触发/完结/记忆沉淀全部继承 V8 事件语义 |
| `memory` | save | memory_policy 校验 + `memory_repository.create_memory` | **真实现**：显式委托记忆（"记住我生日"），source=user_stated，经 R1~R8 政策校验 |
| `world_action` | create / move / use | `world_engine.create_object / move_object / apply_object_action` | **真实现**：V8 实体操作的行动视角（买牛奶=create_object） |
| `environment_query` | query | `world_engine.build_time_context` + WorldEnvironment 读 | **真实现**：返回时间/天气/温度/光照切片（simulated 数据源） |
| `search` | query | —（接口预留） | **unavailable 占位**：返回 unavailable，Record 留痕，评估 info |
| `notification` | send | —（接口预留） | **unavailable 占位**：MVP 通知 = 行动 note（下一轮上下文可见）+ 到期主动汇报走 V7 既有链路 |

设计要点：

1. **reminder 能力是 V9 价值的锚点**：用户"明天提醒我开会"→ WorldEvent(type=reminder, due=明天 8:00) scheduled → 到期 `trigger_due_events` 置 active → 自治 due_action 触发器带动主动汇报 → 用户"面完了"→ interpreter/行动完结 → completed → 记忆沉淀。全链复用 V8，V9 只补"创建入口的主动化"。
2. **world_action 与 V8 interpreter 的词表重叠是刻意的**：interpreter 处理叙事性话语（"切西瓜"），world_action 处理委托性请求（"帮我买牛奶"）；G6 防双重执行（world-integration.md §5）。
3. **query 能力无副作用**：结果只进 ActionResult.payload 与行动 note（本轮说、下轮知道），不直接进本轮回复——回复时序契约（tool-integration.md §3）。

## 5. 未来插件（仅约定，不实现）

新增一个能力的完整清单（五处，全部加法）：

1. `app/services/action/capabilities/<name>.py` 实现 Capability 协议（含 schema）；
2. registry 启动注册一行；
3. `ACTION_CAPABILITY_MAP` 增 ActionType → (capability, action) 映射（如需新 ActionType，先扩 action-model.md 枚举）；
4. 角色资产词表增触发模式 + REQUIRED_PARAMS 表；
5. Action Memory Policy 边界表增行（memory-policy.md §2）+ 评估按需扩 IssueCode。

预留方向：HomeControl（simulated 设备状态 → V8 Object 扩展）、Browser（真实 API 接入位）、Robot（物理执行，明确远期）。这些只出现在本节，tasks.md 不含其任务。

## 6. 能力与工具术语对照

| 通用 Agent 术语 | V9 对应 | 说明 |
|---|---|---|
| Tool / Function | Capability.action | 能力的原子操作，带 schema |
| Tool Call | ActionStep | 由 Planner 装配（非 LLM 产生） |
| Tool Result | CapabilityResult | 归一四字段，不直接进回复 |
| Agent Loop | ActionEngine 生命周期 | created→…→succeeded，六态而非 while 循环 |
| MCP / 插件市场 | CapabilityRegistry | 单进程代码注册，无动态协议 |
