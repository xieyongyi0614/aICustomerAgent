# Memory Evaluation

> Memory 维检查（规则层 app/services/evaluation_rules/memory.py，新增）：检测记忆使用质量——虚构（False Memory）、矛盾、漏用。对照集是本轮实际注入 prompt 的记忆列表（V4 检索产物）。

## 1. 检什么

| 缺陷 | 例子 | 严重度 |
|---|---|---|
| 虚构（Fabrication） | 用户从未说过，角色说"你最喜欢草莓蛋糕" | 最高——直接摧毁信任 |
| 矛盾（Contradiction） | 记忆"用户对花生过敏"，回复请用户吃花生酱 | 高 |
| 漏用（Missed） | 注入了高重要度记忆且与话题强相关，回复完全无视 | 低（信息级） |

判定基准只有两个：**本轮注入的记忆**（ConversationState.memories，digest 已带 id + 内容摘要）与**近期对话窗口**（recent_messages）——"用户说过"的合法出处只有这两处或摘要。

## 2. 规则层

### 2.1 MEMORY_FABRICATION_CANDIDATE（warning，候选级）

```text
reply 命中 recall-marker 词表（"你最喜欢 / 你说过 / 上次你 / 你一直 /
你之前提过 …"，语言级常量 lexicons.py）
  → 提取被引述内容片段
  → 与 injected_memories 内容、recent_messages 做词法重叠匹配
  → 全部无支撑 → issue(MEMORY_FABRICATION_CANDIDATE, warning)
```

规则层**只产候选不定罪**：词法匹配抓不住转述 / 同义改写，也可能漏掉无 marker 的虚构。定罪交给 judge（→ MEMORY_FABRICATION，critical）。

### 2.2 MEMORY_MISSED（info）

injected_memories 中 `importance ≥ 0.7` 且与 user_message 词法重叠 ≥ 阈值的记忆，reply 未覆盖 → info。这是优化信号不是缺陷告警——检索给出了素材而生成没用上，提示 prompt 组装的取舍问题。

## 3. Judge 层

```python
class MemoryJudgement(BaseModel):
    score: float
    codes: list[MemoryIssueCode]  # MEMORY_FABRICATION / MEMORY_CONTRADICTION / MEMORY_MISSED
    memory_ids: list[int]         # 涉及的注入记忆 id（来自 digest，受限引用）
    evidence_quote: str
    confidence: float
```

judge 的固定评审标准：

1. reply 中关于用户的事实断言，逐条在 injected_memories + recent_messages 中找支撑；无支撑即 MEMORY_FABRICATION；
2. 回复是否与任一 active 记忆直接冲突（MEMORY_CONTRADICTION）。

`memory_ids` 强制 judge 只能引用 digest 中列出的记忆 id（受限引用，杜绝编造记忆出处）；evidence_quote 走子串校验。

规则候选与 judge 确认的衔接：规则报了 CANDIDATE 且 judge 同轮给出 FABRICATION → 两条 issue 按 code 去重保留 **FABRICATION（critical）**，CANDIDATE 吸收；judge 缺席（未采样 / 失败）时 CANDIDATE 单独生效（warning），保证候选信号永不丢失。

## 4. 分数

```text
rule_score：CANDIDATE -0.2 / MISSED -0.05
judge_score：MemoryJudgement.score
dimension.score = min(两者)   # FABRICATION critical ⇒ 直接 fail 短路
```

## 5. 已知限制（诚实声明）

- **离线模式注入集不可精确重建**：历史评估时记忆库可能已变化（superseded / 过期）。离线报告的 `meta.context_fidelity = "reconstructed"`，Memory 维结论仅供参考；**权威判定只存在于实时报告**（digest 当时已固化）——这是 digest 必须含 injected_memories 的根本原因。
- 转述型虚构（同义改写）词法抓不住，依赖 judge；采样率 < 1 时存在漏检窗口。
- 虚构的极端形态（角色宣称自己经历了没发生的事）不在 V7.5 范围，词表与评审标准不覆盖自我经历断言。
