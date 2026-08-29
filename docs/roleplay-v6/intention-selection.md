# Intention Selection

## 1. 双阶段：LLM 候选 → 代码校验

```text
输入（全部已有，不新增查询）：
  user_message（本轮输入）
  selected_goal（goal-selection.md 输出，含 reason）
  state 快照（emotion mood/intensity/cause、relationship 四维+tension、scene 摘要、memory top1~2）
  最近对话（context_builder 已加载的窗口，复用）

阶段一（LLM，intention_chain，与 router/turn_analysis/scene_intent 同 gather 并行）：
  → IntentionDecision { intention, confidence, reason }

阶段二（代码，intention_policy.enforce）：
  ① 类型合法性（Literal 校验）
  ② 有效性规则表（intention-model.md §4）
  ③ goal 一致性：intention 应服务于 selected_goal.type
     （user_care 目标下 celebrate_with_user 属越界 → 降级）
  ④ 全部不通过 → continue_topic + reason="策略降级"

输出：ValidatedIntention { intention, reason, goal_id, degraded: bool }
```

## 2. 为什么不在 turn_analysis 里加字段

评估过"扩展 TurnAnalysis 输出 intention"方案，否决：
- turn_analysis 职责是"用户发生了什么"，intention 是"角色想做什么"——主体相反，混入会让 Schema 膨胀且互相污染降级语义；
- 独立 chain 可独立降级、独立测试、独立迭代 prompt。

代价：gather 从 3 链变 4 链（并行，无 wall time 增量，见 architecture.md §4）。

## 3. Intention Chain Prompt 要点（prompts/intention.py）

- 输入：selected_goal 描述+reason、情绪/关系快照、最近对话、本轮用户消息
- 输出约束：只输出 IntentionDecision；**禁止输出数值变化、禁止输出回复文本、reason ≤60 字且为单句决策理由**
- 附合法意图清单与各自一句话语义（12 值全集，LLM 不自由发挥）

## 4. IntentionPolicy 细则

```python
def enforce(decision, selected_goal, state, now) -> ValidatedIntention:
    1. decision is None / 校验异常 → degraded(continue_topic)
    2. 有效性规则表逐条检查（表驱动，core/constants 或 intention 模块常量）
    3. goal 一致性：INTENTION_GOAL_FIT[intention] ⊇ {selected_goal.type}
       否则降级为该 goal 类型的默认 intention（user_care→comfort_user、
       relationship→repair_rapport、conversation→continue_topic、scene→continue_topic）
    4. scene pending action 存在时：表达类 intention（affection/tease/share）
       降级为 continue_topic（承诺优先，见 goal-selection.md §3）
```

## 5. 可观测性

- trace step `intention`：duration + status（ok/degraded/error）
- turn_meta 增加 `intention: {type, reason, goal_id, degraded}`——前端 Debug 面板可展示"角色这轮想做什么、为什么"
- 失败注入验收：intention_chain 抛异常 → SSE 正常、intention 降级 continue_topic、trace error

## 6. 测试切面（详见 testing.md）

同一 Goal + 不同用户输入 → 不同 Intention；同一 Goal+Intention + 不同人格 → 不同表达（人格表达由现有 answer prompt 保证，golden prompt 快照覆盖）。
