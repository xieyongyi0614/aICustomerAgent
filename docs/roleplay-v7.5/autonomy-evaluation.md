# Autonomy Evaluation

> Autonomy 维检查（规则层 app/services/evaluation_rules/autonomy.py + proactive judge 变体，新增）：针对 V7 主动行为——时机、必要性、关系适配、结果价值。评估主体是 `proactive_action`（不是对话轮）。

## 1. 主体与时序

主动消息**不是对话轮**：没有 post_process，不触发状态更新。因此本维有独立挂载点与独立时序：

```text
proactive_executor.execute
  → delivered（消息已发出，save_proactive_turn 落库）
  → fire-and-forget：schedule_proactive_evaluation(action_id)   ← 挂载点 B
       → ContextCollector（从 proactive_actions 行 + 角色状态切片构造）
       → Rule Engine（autonomy 规则）→ Judge（proactive 变体）
       → EvaluationReport(subject=proactive_action)
```

评估失败只 log，**绝不影响已发出的消息**；发送链路不感知评估存在。

## 2. 检什么：四个评价轴

| 轴 | 合理 | 不合理 |
|---|---|---|
| Trigger Reason | 有具体动机（check_in / repair_rapport 映射自真实 goal） | reason 空泛、与 goal 脱节 |
| Timing | 闲置 30 分钟以上、避开静音区、用户不在打字 | 用户 5 分钟前刚回复，角色立刻又主动 |
| Relationship | intimacy 足够支撑这次打扰 | 低亲密度高频问候 |
| Necessity | 内容有增量（关心近况 / 接续话题） | 重复寒暄、无信息量 |

## 3. 规则层（结果审计）

V7 的 AutonomyPolicy 已在**事前**拦下静音 / 冷却 / 深度 / 门槛违规。规则层做的是**事后结果审计**——验证"发出去的"确实满足当时被承诺的条件，捕捉策略与执行之间的缝隙（执行延迟、状态漂移、时钟边界）：

### 3.1 AUTONOMY_TIMING_VIOLATION（warning）

```text
以 delivered_at 时点复核：
  delivered 时刻 ∈ 静音时段                → issue（静音边界竞态）
  delivered 前后 min_user_reply_gap 内用户刚发言 → issue（用户活跃守卫失效）
  距上次主动消息间隔 < effective_interval  → issue（冷却记账缝隙）
  同 episode 已有终态 action 仍发出第二条  → issue（深度 1 被绕过）
```

### 3.2 AUTONOMY_LOW_OUTCOME（info，仅离线聚合）

结果价值不由实时报告判定（发出瞬间无法知道结果），由离线评估器统计：

```text
delivered 后 evaluation_proactive_reply_window_hours(24) 内：
  无 ack 且无用户回复 → 该 action 记结果负信号
离线聚合：ack 率 / 回复率 / 按 intention 分桶 → AUTONOMY_LOW_OUTCOME 直方图
```

这是**群体统计信号**（提示 goal 映射或间隔配置需要调），不是单事件缺陷——单事件"没得到回复"是正常人生。

## 4. Judge 层（proactive 变体）

```python
class ProactiveJudgeResult(BaseModel):
    autonomy: AutonomyJudgement   # codes: AUTONOMY_UNNECESSARY / AUTONOMY_REDUNDANT
    persona: PersonaJudgement     # 主动消息同样要"像亚丝娜"——无人设豁免
```

judge 收到 proactive digest（trigger_type / intention / reason / 距上次交互时长 / intimacy / 发出文本 / 近期对话尾部），固定评审标准：

1. 该触发理由是否足以支撑一次主动打扰（Necessity）；
2. 与近期对话是否重复、有无信息增量（Redundant）；
3. 语气是否符合人设与当前关系阶段（复用 persona 评审标准）。

主体权重：autonomy 0.60 / persona 0.40（memory 维缺席——主动消息没有注入记忆集，不设权重）。主动消息的 First Risk 是"该不该发"，第二才是"发得像不像"。

## 5. 与 AutonomyPolicy 的分工（一个事前、一个事后）

```text
AutonomyPolicy（事前，V7 既有）：决策层——act/wait/ignore，阻止不该发生的发送
Autonomy rules（事后，V7.5）  ：审计层——验证已发送行为的时点合规 + 语义合理性
```

评估**不反悔**：TIMING_VIOLATION 不撤回消息、不修改 proactive_actions 状态。若审计频繁报警，说明策略参数或执行实现有 bug——修的是策略层，评估只负责把证据摆出来。

## 6. 已知局限

- 主动行为当前仅 `send_message` 一种 type、`check_in / repair_rapport` 两种意图，judge 评审标准按此窄域写死；意图扩展时评审标准随 PROACTIVE_INTENTION_MAP 同步扩充。
- 结果观察窗 24h 内用户可能只是没上线——LOW_OUTCOME 是弱信号，只进离线直方图，永不参与 verdict。
- tick 循环尚未接入 main.py lifespan（V7 遗留项）：挂载点 B 在接入前只能被测试与手动 tick 触发，本维实时报告产出依赖该前置收口。
