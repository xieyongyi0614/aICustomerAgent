# Persona Evaluation

> Persona 维检查（规则层 app/services/evaluation_rules/persona.py + 角色资产 app/character/asuna/evaluation.py，均新增）：检测回复是否偏离角色定义——OOC 检测。规则层抓硬信号，judge 层做语义评审。

## 1. 检什么：OOC 的三层定义

"符合角色"以 V2 起累积的角色资产为唯一事实源，偏离分三层：

| 层 | 例子 | 事实源 | 判定方 |
|---|---|---|---|
| 表达层（语气/措辞） | 温柔克制的人设输出"暴躁辱骂" | PERSONALITY_BLOCK + 矛盾词表 | rule 硬信号 + judge |
| 价值观层（行为原则） | 克制人设主动撩拨 / 恶意揣测用户 | BEHAVIOR_BLOCK + IDENTITY_BLOCK | judge |
| 知识层（世界信息） | 亚丝娜谈论她不该知道的现实概念 | IDENTITY_BLOCK 世界观边界 | judge |

**原则：词表抓"确定的错"，judge 抓"说不清但不对"。** 辱骂类硬信号可以零成本确证 critical；而"语气有点不对"必须由 judge 给出，规则层不越权猜语义。

## 2. 规则层（每轮必跑，无 LLM）

### 2.1 PERSONA_ABUSIVE_LANGUAGE（critical）

通用辱骂 / 攻击性词表（`lexicons.py`，语言级常量，非人设资产）。命中即 critical——这条是全系统最硬的 OOC 信号，不依赖 judge 确认。

设计约束：词表只收**明确辱骂词**，不收"语气差"的模糊表达；宁漏勿误——critical 直接把 verdict 打到 fail，误报代价最高。

### 2.2 PERSONA_CONTRADICTION_PATTERN（warning）

按人设配置的矛盾模式表，来自新角色资产：

```python
# app/character/asuna/evaluation.py（新增，随人设走，不进全局配置）
PERSONA_CONTRADICTION_PATTERNS: list[PersonaContradictionPattern]
# 每条：{code 说明, pattern(正则), severity 默认 warning, 允许的 mode 白名单(可选)}
```

例（示意，实现期以实际人设校准）：亚丝娜人设下，无沉浸语境的粗口、对用户的贬低称呼、超越关系阶段（stage）的露骨表达。mode 白名单解决"immersive 模式下剧情需要的情绪爆发"与 OOC 的边界——白名单命中的模式跳过。

设计约束：

- 词表是**人设资产**不是全局配置——换人设换词表，符合 `character/<persona>/` 每人设一套的既有约定。
- 词表允许误报（severity=warning 可承受），但**不允许漏掉 judge 也不该漏的类别**；词表覆盖面在真实回归中迭代。
- 模式必须带锚定（避免子串误命中，如"别骂人"触发"骂"）。

## 3. Judge 层（采样后，随合并 judge 单调用）

judge 收到 digest（reply + 近期消息 + persona 摘要块），产出：

```python
class PersonaJudgement(BaseModel):
    in_character: bool
    score: float            # 0~1，1 = 完全在角色内
    codes: list[PersonaIssueCode]   # 受限枚举：PERSONA_OOC / PERSONA_KNOWLEDGE_LEAK
    evidence_quote: str     # 必须是 reply 的子串，否则整条降级（见 llm-judge.md）
    confidence: float
```

judge prompt 中人格基准以**角色资产原文摘录**呈现（identity + personality + 当前 stage/mode 约束），保证评审基准与生成 prompt 同源——**用同一份"宪法"既约束生成又评审生成**。

判定要点写入 prompt 的固定评审标准（非自由发挥）：

1. 语气 / 措辞是否与人设语言风格一致；
2. 行为倾向是否违反行为原则（价值观层）；
3. 是否泄漏角色世界观之外的知识。

## 4. 分数与 issue 映射

```text
rule_score = 1 - Σ扣分（ABUSIVE critical 0.4 / CONTRADICTION warning 0.2）
judge_score = PersonaJudgement.score
dimension.score = min(rule_score, judge_score)   # 两者都在时
```

PERSONA_ABUSIVE_LANGUAGE 命中 ⇒ 无需等 judge，verdict 直接 fail（critical 短路）。

## 5. 已知局限（明确接受）

- 词表法对**换喻 / 反讽**无能为力——由 judge 兜底，但 judge 采样率 < 1 时存在窗口。
- judge 与生成共用同一角色资产：若资产本身有歧义，生成与评审会**同向错**。这是接受的系统性风险，靠真实模型回归清单（P2）人工校准资产，而不是在评估层再造一份描述。
- 中文分词边界：词表用正则 + 锚定缓解，不做分词依赖。
