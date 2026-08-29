# Behavior Evaluation

> Behavior 维检查（规则层 app/services/evaluation_rules/behavior.py，新增）：针对 V6.5 的动作层——预算越界、接触越权、连续单调、表达浓度。**接近 100% 规则可判，不引入 LLM**。

## 1. 为什么这维不需要 judge

动作在本系统是文本层 `*动作描写*`，V6.5 的 `observe_budget` 已经用正则 + 接触词表对回复做只读观测并写入 trace（budget_observer step）。判定所需的一切都是**确定性可数的**：

- 预算上限是引擎给定值（ActionBudget.max_action_desc）；
- 动作数量是正则计数；
- 接触等级是词表分级。

语义模糊的"动作是否得体"不在这维讨论——那是 persona（价值观层）与 stage 约束的职责。**规则能判的不给 LLM**，是 V7.5 成本与可测性的底线。

## 2. 输入

| 输入 | 来源 |
|---|---|
| ActionBudget（max_action_desc / physical_contact / emotion_expression / strategy） | trace.behavior_meta（behavior_engine 产物） |
| observed_action_count / contact_level | trace 预算观测（observe_budget 结果） |
| 最近 N 轮的每轮动作序列（动作类别标签） | 近期消息逐轮跑 observe_budget 的轻量重放（仅计数，不重跑管线） |

## 3. 规则集

### 3.1 BEHAVIOR_BUDGET_EXCEEDED（warning）

```text
observed_action_count > max_action_desc → issue
```

与 budget_observer 的区别：observer 只记录 violation 进 trace（观测），本规则**扣分并出具 issue**（判定）。同一正则，两个消费者。

### 3.2 BEHAVIOR_CONTACT_VIOLATION（warning）

```text
reply 命中接触词表等级 > budget.physical_contact → issue
（physical_contact: none < light < moderate；no_action 策略下预算清零时任何动作/接触都算越界）
```

### 3.3 BEHAVIOR_ACTION_MONOTONY（warning）——本次设计的核心增量

针对 V6.5 最典型的退化模式：

```text
连续：摸头 → 握手 → 拥抱 → 脸红    （单轮都合规，连看就是动作堆砌）

滑窗 = 最近 evaluation_behavior_monotony_window(5) 轮
每轮动作按类别归一（动作动词表 → 接触/表情/姿态/位移 4 类）
同类别在窗内出现次数 ≥ evaluation_behavior_monotony_threshold(3) → issue
evidence = 窗内动作原文序列
```

单轮看每一处都在预算内，**序列看是单调循环**——这是"每轮检查"抓不到、必须引入跨轮窗口的原因。

### 3.4 BEHAVIOR_EXPRESSION_MISMATCH（info）

emotion_expression 档位（subtle/natural/rich）与实际情绪表达密度（感叹 / 情绪词频）明显偏离 → info。校准型信号，不构成 warn/fail。

## 4. 分数

```text
rule_score = 1 - Σ扣分（三条 warning 各 0.2，info 0.05）
judge_score = None（本维无 judge）
dimension.score = rule_score
```

采样关闭（sample_rate=0）时本维**照常完整可用**——五个维度中 behavior 是唯一完全不依赖 LLM 的，这也是它作为 Rule Engine 首个落地规则集（V7.5-005）的原因。

## 5. 已知局限

- 动作类别归一靠词表，新动作写法可能归类失败 → 计入"其他"，不参与单调统计（宁可漏不可错）。
- 重放历史轮只做正则计数，不做完整管线重放——历史轮的预算值取当时的 behavior_meta（trace 内存容量有限时降级为"仅本轮"窗口）。
- `*...*` 之外的叙述性动作（无星号包裹）不在计数范围——与 observe_budget 口径保持一致，不另立标准。
