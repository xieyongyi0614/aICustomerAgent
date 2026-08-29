# Evaluation Model

> 评估域模型（app/models/evaluation.py，新增）：EvaluationReport 是唯一结果载体。本文定义模型、Issue 编码表（全系统唯一事实源）、分数语义、上下文摘要与生命周期。

## 1. 领域模型

```python
# app/models/evaluation.py（新增）
class EvaluationDimension(StrEnum):
    PERSONA = "persona"
    EMOTION = "emotion"
    MEMORY = "memory"
    BEHAVIOR = "behavior"
    AUTONOMY = "autonomy"

class EvaluationSubjectKind(StrEnum):
    TURN = "turn"                        # 对话轮（subject_id = turn_id）
    PROACTIVE_ACTION = "proactive_action"  # 主动行为（subject_id = proactive action id）
    OFFLINE_BATCH = "offline_batch"      # 离线批量运行（subject_id = run id）

class IssueSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

class IssueCode(StrEnum):
    # 编码表见 §3；规则与 judge 共用同一枚举，禁止自由文本编码
    ...

class Issue(BaseModel):
    code: IssueCode
    severity: IssueSeverity
    dimension: EvaluationDimension        # persona/emotion/memory/behavior/autonomy
    message: str                          # 由代码模板生成，LLM 不自由撰写
    evidence_quote: str = ""              # 判定依据原文（≤80 字符，可为空）
    source: Literal["rule", "llm"]

class DimensionScore(BaseModel):
    dimension: EvaluationDimension
    score: float                          # 0.0 ~ 1.0
    rule_score: float | None = None       # 规则层推导分（1 - Σ扣分）
    judge_score: float | None = None      # LLM judge 分（缺席 = 未采样或失败）
    issue_codes: list[IssueCode]

class EvaluationReport(BaseModel):
    id: str                               # uuid
    subject: EvaluationSubjectKind
    subject_id: str
    user_id: str
    character_id: str
    scores: dict[EvaluationDimension, DimensionScore]   # 只含有分维度，缺席不填 0
    overall_score: float | None           # 按 subject 权重表加权；offline_batch 为 None
    verdict: Literal["pass", "warn", "fail"]
    issues: list[Issue]
    context_digest: dict                  # 有界摘要，结构见 §4
    meta: EvaluationMeta                  # model_name / judge_used / context_fidelity /
                                          # rule_codes_fired / duration_ms
    created_at: datetime
```

设计约束：

- **scores 缺席 ≠ 0 分**：某维未启用 / 未采样 / judge 失败时整维缺席。0 分是"最差"，缺席是"不知道"——两者语义必须分开。
- Issue.message 由服务端按 `code → 中文模板` 生成，evidence_quote 才是 judge 的自由度出口（且受子串校验约束，见 llm-judge.md）。
- Report **不可变**：创建后不更新分数；人工复核（false_positive 标记）是后续可选特性，不在 V7.5 范围。

## 2. 分数语义

```text
规则层：rule_score = clamp(1 - Σ(penalty(issue.severity)), 0, 1)
        penalty: critical=0.4  warning=0.2  info=0.05（settings 可调）

合并层：某维同时有 rule_score 与 judge_score 时，dimension.score = min(两者)
        只有其一 → 用其一；两者都无 → 维度缺席

整体层：overall_score = Σ(dimension.score × weight)，权重按主体取表
        turn             : persona 0.35 / emotion 0.20 / memory 0.20 / behavior 0.25
        proactive_action : autonomy 0.60 / persona 0.40
                           （memory 维缺席：主动消息无注入记忆集，不设权重）

判定：verdict = fail    当存在任一 critical issue 或 overall < evaluation_fail_score(0.6)
              warn     当 overall < evaluation_warn_score(0.85)
              pass     其余
offline_batch 的 overall_score 恒为 NULL，verdict 退化为按 issues 映射：
有 critical → fail；无 critical 有 warning → warn；否则 pass。
```

为什么是 min 而不是加权平均：**平均会稀释违例**——规则抓到的硬违例（如辱骂）可能被 judge 的 0.9 分平均成 0.75，看起来"还不错"。评估的目的是找问题，取 min 表达"质量下界"。

为什么权重表按主体分：对话轮的主体是"人格 + 行为"（persona+behavior 占 0.60）；主动消息没有动作预算概念，核心风险是"该不该发、发得像不像"——autonomy+persona 即全部权重。emotion 并入 persona 评审不单列；memory 维因主动链路无注入记忆集而缺席。

## 3. Issue 编码表（唯一事实源）

| code | 维度 | 默认 severity | 判定方 | 含义 |
|---|---|---|---|---|
| PERSONA_ABUSIVE_LANGUAGE | persona | critical | rule | 辱骂 / 攻击性词表硬命中 |
| PERSONA_CONTRADICTION_PATTERN | persona | warning | rule | 命中角色 OOC 矛盾词表（人设不允许的表达模式） |
| PERSONA_OOC | persona | warning | llm | judge 判定语气 / 价值观不符人格 |
| PERSONA_KNOWLEDGE_LEAK | persona | warning | llm | 说出角色设定之外的世界知识 |
| EMOTION_UNTRIGGERED_SHIFT | emotion | warning | rule | 弱 / 无事件下 mood 发生切换 |
| EMOTION_TEXT_STATE_CONFLICT | emotion | warning | rule 候选 + llm 确认 | 回复文本情绪信号与当前 mood 冲突（词表候选，judge 复核裁决） |
| EMOTION_OVERSHIFT | emotion | warning | llm | judge 判定情绪强度 / 转向过度 |
| MEMORY_FABRICATION_CANDIDATE | memory | warning | rule | recall-marker 词表命中且注入记忆 / 近期对话无支撑 |
| MEMORY_FABRICATION | memory | critical | llm | judge 确认虚构记忆 |
| MEMORY_CONTRADICTION | memory | warning | llm | 回复与 active 记忆矛盾 |
| MEMORY_MISSED | memory | info | rule/llm | 高重要度相关记忆未被使用 |
| BEHAVIOR_BUDGET_EXCEEDED | behavior | warning | rule | `*动作*` 数量超 ActionBudget.max_action_desc |
| BEHAVIOR_CONTACT_VIOLATION | behavior | warning | rule | 身体接触等级超 physical_contact 预算 |
| BEHAVIOR_ACTION_MONOTONY | behavior | warning | rule | 滑窗内同类动作连续命中 ≥ 阈值 |
| BEHAVIOR_EXPRESSION_MISMATCH | behavior | info | rule | emotion_expression 浓度偏差 |
| AUTONOMY_TIMING_VIOLATION | autonomy | warning | rule | delivered 时点命中静音 / 用户活跃 / 间隔不足（结果审计） |
| AUTONOMY_REDUNDANT | autonomy | warning | llm | 与近期消息重复、无信息增量 |
| AUTONOMY_UNNECESSARY | autonomy | warning | llm | judge 判定触发理由不足以支撑主动打扰 |
| AUTONOMY_LOW_OUTCOME | autonomy | info | rule（仅离线） | 24h 窗口内无 ack 无回复的结果统计信号 |

severity 是**默认值**：规则命中即采用默认；judge 不产生 severity，由 code 映射。调整 severity 属于改编码表（模型层），不是运行时配置。

## 4. Context Digest（有界摘要）

报告不存完整 prompt，只存 digest——它既是 judge 的输入，也是报告里唯一留存的上下文证据：

```python
# digest 结构（构造于 app/services/evaluation_context.py）
{
  "user_message": str,            # ≤200 字符
  "reply": str,                   # ≤400 字符
  "recent_messages": [...],       # 最近 6 条，每条 ≤120 字符，附该轮 mood_after（可缺，
                                  #  取自 emotion_history；供 emotion judge 的摇摆判定）
  "injected_memories": [...],     # ≤5 条：{id, type, content ≤40 字符}
  "emotion": {mood_before, mood_after, intensity, event, magnitude},
  "behavior": {max_action_desc, observed_action_count, contact_level,
               strategy, emotion_expression},
  "state": {mood, energy, stage, intimacy},
  "proactive": {...} | None,      # 仅主动主体：trigger_type/intention/reason/timing
}
```

- 总字符预算 `evaluation_max_digest_chars=2000`，构造器负责截断（后截低优先级字段）。
- digest 是**判定依据的最小集**：事后人工看报告时，凭 digest 应能独立复核每个 issue 是否成立。

## 5. 生命周期

```text
created（评估完成，一次性写入）
   │  不可变；只能被读取（debug API / 离线聚合）
   ▼
retention prune（写入时惰性清理 created_at < now - retention_days 的旧行）
```

- 无"进行中"态：评估在单个后台任务内完成收集→判定→合并→落库，中途失败就不产生报告。
- 人工复核（确认误报 / 标注反馈）属 V8+，V7.5 只保证报告可追溯、可重放（凭 digest）。

## 6. 配置组（app/core/settings.py 新增 evaluation_*）

| 配置 | 默认 | 说明 |
|---|---|---|
| `evaluation_enabled` | True | 总开关；False 时挂载点直接跳过 |
| `evaluation_persona_enabled` 等五维开关 | True | 按维启停 |
| `evaluation_llm_judge_enabled` | True | judge 层开关（False = 纯规则模式） |
| `evaluation_llm_judge_sample_rate` | 1.0 | judge 采样率，按 request_id 确定性哈希 |
| `evaluation_judge_profile` | "" | judge 用 LLM profile，空则跟随 default |
| `evaluation_penalty_critical/warning/info` | 0.4 / 0.2 / 0.05 | 扣分表 |
| `evaluation_fail_score` / `evaluation_warn_score` | 0.6 / 0.85 | verdict 阈值 |
| `evaluation_overall_weights_json` | §2 权重表 | 按主体加权 |
| `evaluation_behavior_monotony_window` / `_threshold` | 5 / 3 | 连续动作滑窗 |
| `evaluation_proactive_reply_window_hours` | 24 | 主动结果观察窗（离线聚合用） |
| `evaluation_retention_days` | 30 | 报告保留期 |
| `evaluation_max_digest_chars` | 2000 | digest 上限 |

约束：全部阈值走 settings，禁止在规则实现里写魔法数字（与全库约定一致）。
