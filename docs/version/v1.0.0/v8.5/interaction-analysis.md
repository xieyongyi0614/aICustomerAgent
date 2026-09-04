# V8.5 M2：Interaction Analyzer（交互分析器）

> 把"一轮互动"翻译成结构化信号（发生了什么 × 感受如何 × 有多显著 × 有多新鲜），作为关系演化的唯一上游输入。V5 的 9 种事件类型是"delta 载体"，本文的信号是"语义层"——两者分层，不合并。

## 1. 信号模型

```python
InteractionKind = Literal[
    "smalltalk",         # 闲聊寒暄
    "self_disclosure",   # 用户自我袒露（分享心事/秘密/脆弱面）
    "support",           # 用户对角色的情绪支持/安慰
    "request_help",      # 用户求助
    "gratitude",         # 用户表达感谢
    "humor",             # 玩笑/幽默互动
    "promise",           # 承诺（quality 复用为 outcome：positive=兑现 negative=违背）
    "teaching",          # 用户教角色/给建议
    "shared_activity",   # 共同完成一件事
    "appreciation",      # 用户赞美/肯定
    "criticism",         # 用户批评/抱怨
    "boundary_violation",# 越界言行
    "conflict",          # 争吵
    "ambient",           # 无特定语义的陪伴（长互动/日常在场）
]

class InteractionSignal(BaseModel):
    kind: InteractionKind
    quality: Literal["positive", "neutral", "negative"]
    salience: float          # 0~1 显著度（LLM 置信度或启发式固定值）
    novelty: float           # 0~1 新颖度 = 1/(1+窗口内同 kind+quality 重复次数)，代码计算
    cause: str = ""          # ≤50 字，进账本 cause
```

分层原则：kind 描述"发生了什么"，quality 描述"感受如何"，二者正交（一次幽默可以冷场收场：humor + negative）。显著度回答"多重要"，新颖度回答"是不是老一套"——**这四个量共同决定演化动力学**（evolution-engine.md §3）。

## 2. 双通道检测（确定性优先，P0 零新增 LLM 调用）

### 通道 A：启发式词表（零成本，每轮必跑）

`app/character/asuna/relationship_lexicon.py` 资产表驱动，模式匹配用户消息 + 角色回复：

| 线索（示例） | kind / quality | salience |
|---|---|---|
| 谢谢/多亏了你/太感谢 | gratitude / positive | 0.5 |
| 对不起（冲突语境）/我错了 | recovery 词表（M5 消费，**不产信号**） | — |
| 我答应你 / 说到做到 / 兑现 | promise / positive | 0.6 |
| 你怎么这样 / 说话不算话 | promise / negative | 0.6 |
| 说真的，其实我一直… / 别告诉别人 | self_disclosure / positive | 0.6 |
| 别过界 / 不许这样说 | boundary_violation / negative | 0.7 |
| 你太厉害了 / 真有你的 | appreciation / positive | 0.4 |

- 词表只做**高置信命中**（宁缺毋滥，V8 解释器同款纪律）；未命中不是零信号——降级到通道 B 的既有输出。
- 敏感词表（冒犯/越界类）宁可误报也不漏报（负向信号漏检的代价大于误检）。

### 通道 B：既有 LLM 结构化输出扩展（零新增调用）

`turn_analysis_chain` 的 `RelationshipEventDecision` 旁增可选字段 `interaction_signal`（kind/quality/salience/cause），与 role_router 等四链并行完成，无额外请求。旧输出缺该字段时整体走通道 A + 事件映射兜底。

### 通道 C：采样增强（P1，默认关）

启发式低置信命中（0 < salience < 0.5）且 `rel_signal_llm_enabled=true` 时，采样一个小型分类调用（request_id 哈希确定性采样，同 V7.5 judge 模式；失败/超时静默回落通道 A 结果）。接口与配置本 Task 先行，实现留 P1。

## 3. 证据窗（EvidenceWindow）

```text
每用户环形队列，容量 rel_signal_evidence_window=20，进程内存维护
用途：novelty 计算（§1）+ 边际递减计数（M3 §3）
重建：冷启动/重启后从 relationship_events 近 N 行（type/magnitude/cause/created_at）
      近似重建——账本行无 quality，按"强档≈positive、弱档≈neutral"映射，够用
生命周期：state_update 用户写锁内更新；不落库、不持久化、不跨进程共享
```

信号本身不落库（架构纪律）：落库的只有升格后的事件/里程碑/冲突/快照四类"因"。

## 4. 信号 → 事件映射矩阵（纯函数）

信号不直接产生 delta；先映射为 V5 事件类型（RelationshipEventDecision 语义），再走既有查表。quality=neutral 一律降为 weak 档；映射表驱动、逐条单测：

| InteractionKind | quality | → RelationshipEventType | magnitude 规则 |
|---|---|---|---|
| self_disclosure | positive | intimate_moment | salience≥0.7→strong / ≥0.4→normal / else weak |
| support | positive | user_care | 同上 |
| gratitude / appreciation | positive | praise | 同上 |
| humor / shared_activity | positive | warm_moment / long_interaction | 同上 |
| smalltalk / ambient | positive | long_interaction | 一律 weak |
| request_help | positive（角色帮上忙） | user_care | 同上 |
| teaching | positive | user_help | 同上 |
| promise | positive（兑现） | promise_kept | 同上 |
| promise | negative（违背） | promise_broken | 同上 |
| criticism | negative | criticized | 同上 |
| boundary_violation | negative | boundary_violation | 一律 normal 以上 |
| conflict | negative | conflict | salience≥0.7→strong |
| 任意 kind | neutral | 对应类型 | 一律 weak |
| 无命中且无 LLM 输出 | — | none（不落账） | — |

一次互动至多产生 1 个主信号（显著性最高者）；同轮多线索并存时弱信号并入证据窗但不升格（防账本噪声，V5"type=none 不建行"口径的延伸）。

## 5. 与既有链路的关系

- `RelationshipEventDecision`（V5）继续存在并作为映射终点——delta 表、限速、账本、评估全部在事件层，对既有代码零破坏。
- 事件行新增 `signal_cause`？不加：cause 字段沿用（signal.cause 直通），信号细节只进证据窗。
- `memory_replay` 补记路径（V5 既有）不产生信号、不进证据窗，只打折落账（防回放稀释 novelty 基线）。

## 6. 验收标准

- 词表命中矩阵逐条正确；敏感类（越界/冲突）误放行率为零（给定语料集）。
- LLM 字段缺失/解析失败 → 通道 A 独挑，回合零阻塞。
- novelty：同类重复 0/1/3 次 → 1.0 / 0.5 / 0.25。
- 映射矩阵：neutral 降档、conflict strong 分档、promise outcome 语义正确。
- 证据窗重建与内存窗口在"同 kind 计数"上等价（容许 quality 近似）。
- 全链 P0 零新增 LLM 请求（llm 调用计数断言）。
