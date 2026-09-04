# V9 Testing（测试分层与场景套件）

> 行动有外部副作用，测试必须同时证明两件事：**关闭时逐字节回到 V8.5**（没改行为），**开启时副作用精确落位**（做了真做、败了真报）。全部确定性（无真实 LLM），时间敏感全部注入时钟。

## 1. 测试分层

| 层 | 位置 | 内容 | 纪律 |
|---|---|---|---|
| Domain 单测 | `tests/unit/test_action_models.py` | 模型校验（枚举边界、params/dedupe_key 规范化、六态迁移表全格：合法迁移/非法返回 None）、GateDecision/ActionEffect 构造 | 纯函数零 IO |
| 检出/闸门单测 | `tests/unit/test_action_detector.py`、`tests/unit/test_action_planner.py` | 词表矩阵逐条（正/反/问句守卫/多意图取优先）、时间短语解析表、G1~G6 正反例、ACTION_CAPABILITY_MAP 全覆盖 | 注入 now 与世界快照 |
| 能力单测 | `tests/unit/test_capability_registry.py`、`tests/unit/test_capabilities.py` | 注册表（重名拒绝/schema 校验）、各能力 execute（播种世界/记忆夹具，断言宿主副作用与 CapabilityResult） | 真实仓储夹具 |
| 集成 | `tests/integration/test_action_pipeline.py`、`tests/integration/test_action_world_bridge.py`、`tests/integration/test_action_memory_bridge.py` | 第 9 步全链（intent→闸门→执行→四通道）、世界写通道、记忆投递幂等 | action_enabled=true 夹具 |
| e2e | `tests/e2e/test_debug_actions.py` | /debug/actions 列表/详情/重试/取消 | API 层 |
| 场景套件 | `tests/v9/`（§2） | 七套件 + 声明式场景 + 性能护栏 | 单命令全绿 |

夹具约定（`conftest`）：`action_enabled` 默认 false（与生产出厂一致），action 夹具显式开启 + 播种世界数据；`action_memory_policy_json`/`action_relationship_enabled` 按 suite override；时间用 FakeTimeProvider 注入（V8 同款）。

## 2. tests/v9/ 七套件

| # | 套件 | 覆盖 | 关键断言 |
|---|---|---|---|
| 1 | `test_action_planning.py` | Planning Test | "提醒我晚上买牛奶"→confident intent→六闸门→plan(steps=[reminder.create])→succeeded；"提醒我开会"（无时间）→ambiguous→cancelled(gate=ambiguous_params)；问句"你能提醒我吗"→None；24h 重复→duplicate |
| 2 | `test_capability_system.py` | Capability Test | 注册表语义；reminder→WorldEvent(scheduled, due 正确)；memory→policy 校验+落库(source=user_stated)；world_action 三动作；environment_query 只读零写；search/notification→unavailable |
| 3 | `test_execution_engine.py` | Execution Test | 状态机全链（created→…→succeeded）；超时→timeout→重试→succeeded；per-user 锁互斥（与 save_turn 并发注入）；重入保护（非 planned 拒执行）；expires_at 过期→cancelled |
| 4 | `test_action_world_update.py` | World Update Test | 第 8→9 步顺序契约（双命中时 G6 否决）；世界写失败→行动 failed(permanent) 不假成功；行动事件进下一轮世界切片与行动段双通道；world_enabled=false→依赖世界行动 unavailable |
| 5 | `test_action_memory_policy.py` | Memory Policy Test | 边界表逐格（沉淀/不沉淀/importance/source）；R1~R8 零豁免（ai_inferred 不出现）；幂等（effects 去重）；失败委托沉淀 |
| 6 | `test_autonomy_action.py` | Autonomy Action Test | action_facts 注入（不传→与 V8 逐位一致）；poll_due_actions 幂等（reported_by_autonomy 置位）；到期汇报走八步闸门+静音顺延；autonomy_action_enabled=false 零路径 |
| 7 | `test_failure_recovery.py` | Failure Recovery Test | transient 退避重试曲线（backoff×2^n）；超限→failed 终态；permanent 不重试；失败→行动段"待补救"→下轮补救行动闭环；integrate 单通道失败不冒泡 |

声明式场景（`tests/v9/scenarios/*.json`，V8 同款格式）：**牛奶全链**（委托→create_object→行动段→后续"喝掉"→use_object）、**提醒全链**（委托→WorldEvent→时间推进→到期→主动汇报→"办完了"→completed→记忆沉淀）、**失败补救链**（无时间委托→ambiguous→下轮澄清→confident→succeeded）。各含正反例（不触发消息、闸门否决消息）。

## 3. 性能护栏（常驻断言）

| 预算 | 断言 |
|---|---|
| 检出（每轮，纯函数） | < 1ms（词表匹配 + 参数抽取） |
| 第 9 步（含执行 + 四通道） | < 50ms（simulated 能力无外部 IO） |
| action_ctx 装配 + 渲染 | < 5ms、段 ≤ action_context_char_budget |
| action_facts 装配 | < 5ms、降级（异常→{}）零影响 |
| 开关关闭路径 | action_enabled=false 时第 9 步 + 检出 + 渲染全部零执行（调用计数=0） |

## 4. 回归底线

1. `action_enabled=false`：全量既有测试（1120+）零回归；`tests/golden/` 字节不变。
2. `action_enabled=true` + 非行动消息：全链路字节不变（检出 None → 挂载点全部短路）。
3. V2~V8.5 专项回归逐版抽测（V4 记忆 / V5 关系 / V6 目标 / V7 自治 / V7.5 评估 / V8 世界）——V9-010 收口时全量跑一次。
4. World 一致性规则（V8-015）与 action_overclaim 并存不冲突：前者管"宣称物品存在 vs 世界"，后者管"宣称行动完成 vs 记录"。
5. 全部新测试全局命名唯一（pytest-xdist），单命令 `pytest tests/` 可跑全绿。
