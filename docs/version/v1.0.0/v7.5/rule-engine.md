# Rule Engine

> 规则引擎（app/services/evaluation_rules/，新增）：V7.5 的确定性判定层。纯函数、零 LLM、零成本、每轮必跑、可表驱动测试。本文定义规则协议、扣分推导、注册表隔离与全部规则清单。

## 1. 定位：Rule Based + LLM Judge 的分工线

```text
Rule（确定性）                    LLM Judge（语义性）
─────────────────────────        ─────────────────────────
可数 / 可正则 / 可查表            说不清但不对
预算计数、词表硬信号、            像不像角色、情绪过不过度、
时序审计、窗口统计                记忆有没有支撑
每轮必跑，成本 0                  按 sample_rate 采样
结果可复现、可 golden             结果可降级、需容错
```

**分工铁律：规则能判的绝不给 LLM；规则只能产候选的，定罪权在 judge。** 全部 19 条 Issue 编码中 11 条由规则直接判定或产候选（见 evaluation-model.md §3）。

## 2. 规则协议

```python
# app/services/evaluation_rules/__init__.py（新增）
class EvaluationRule(Protocol):
    code: IssueCode                      # 一条规则对应一个 IssueCode
    dimension: EvaluationDimension
    subjects: tuple[EvaluationSubjectKind, ...]   # 适用主体；双主体规则声明两者
    def evaluate(self, ctx: EvaluationContext) -> Issue | None: ...
```

设计约束：

- **纯函数**：入参只有 ctx，无 IO、无 LLM、无全局可变状态；所需数据由 ContextCollector 一次性切片备齐。历史窗口数据（如动作滑窗）也进 ctx，规则不回头查库。
- **主体过滤在注册表**：执行集 = RULES × 维度开关 × `subjects` 命中当前评估主体。TIMING_VIOLATION 声明仅 `proactive_action`，turn 评估不会执行它；ctx 缺失输入静默跳过只是兜底防线，不是过滤机制。
- **单 issue 输出**：一条规则一次至多产一条 issue（多命中合并 evidence）；触发即按 code 的默认 severity 扣分。
- **异常自隔离**：注册表逐条 try/except，单规则异常只 trace，不影响其余规则与维度——规则之间**零依赖、零顺序假设**。
- 规则永不修改 ctx；永不抛出到引擎层。

## 3. 扣分推导

```text
维度 rule_score = clamp(1 - Σ penalty(命中规则的 severity), 0, 1)
penalty(critical/warning/info) = evaluation_penalty_* 配置（默认 0.4 / 0.2 / 0.05）
无规则命中 → rule_score = 1.0
该维规则集为空或全维未启用 → 维度缺席（不产 1.0 假满分）
```

severity → penalty 的映射只在引擎合并处发生一次；规则本身只报 code + evidence，**不携带分数**——扣分策略调整不改规则代码。

## 4. 注册表与分发

```python
RULES: list[EvaluationRule] = [
    behavior.BUDGET_EXCEEDED, behavior.CONTACT_VIOLATION,
    behavior.ACTION_MONOTONY, behavior.EXPRESSION_MISMATCH,
    persona.ABUSIVE_LANGUAGE, persona.CONTRADICTION_PATTERN,
    emotion.UNTRIGGERED_SHIFT, emotion.TEXT_STATE_CONFLICT,
    memory.FABRICATION_CANDIDATE, memory.MISSED,
    autonomy.TIMING_VIOLATION,
]
# 运行时按 dimension × evaluation_<dim>_enabled 过滤后执行
```

规则按维度分文件：`behavior.py / persona.py / emotion.py / memory.py / autonomy.py`；语言级词表（辱骂词、recall-marker、动作类别表）集中 `lexicons.py`；人设词表（OOC 矛盾模式）不在 lexicons——它属于 `app/character/asuna/evaluation.py` 人设资产，由 persona 规则加载。

## 5. 规则清单汇总

| 规则 | 维度 | severity | 关键输入 | 文档 |
|---|---|---|---|---|
| ABUSIVE_LANGUAGE | persona | critical | reply × 辱骂词表 | persona-evaluation.md §2.1 |
| CONTRADICTION_PATTERN | persona | warning | reply × 人设矛盾模式 | persona-evaluation.md §2.2 |
| UNTRIGGERED_SHIFT | emotion | warning | emotion_history 最新行 | emotion-evaluation.md §2.1 |
| TEXT_STATE_CONFLICT | emotion | warning | reply 情绪词 × mood_after | emotion-evaluation.md §2.2 |
| FABRICATION_CANDIDATE | memory | warning | reply marker × 注入记忆/近期消息 | memory-evaluation.md §2.1 |
| MISSED | memory | info | 高重要度注入记忆 × reply 覆盖 | memory-evaluation.md §2.2 |
| BUDGET_EXCEEDED | behavior | warning | observe_budget 计数 × budget | behavior-evaluation.md §3.1 |
| CONTACT_VIOLATION | behavior | warning | 接触词等级 × physical_contact | behavior-evaluation.md §3.2 |
| ACTION_MONOTONY | behavior | warning | 近 5 轮动作类别滑窗 | behavior-evaluation.md §3.3 |
| EXPRESSION_MISMATCH | behavior | info | expression 档位 × 表达密度 | behavior-evaluation.md §3.4 |
| TIMING_VIOLATION | autonomy | warning | delivered 时点 × 静音/间隔/深度 | autonomy-evaluation.md §3.1 |

（judge 专属 8 个 code 不在注册表：PERSONA_OOC / PERSONA_KNOWLEDGE_LEAK / EMOTION_OVERSHIFT / MEMORY_FABRICATION / MEMORY_CONTRADICTION / AUTONOMY_REDUNDANT / AUTONOMY_UNNECESSARY，及仅离线的 AUTONOMY_LOW_OUTCOME。）

## 6. 可测性

- 每条规则独立表驱动用例：命中 / 不命中 / 边界 / ctx 缺失输入容错，四类必备。
- 判定结果 = (是否产 issue, code, severity, evidence 非空) 的组合断言——**不校验 message 文案**（模板属于实现细节）。
- 全部规则用例不建 DB、不注入 LLM（ctx 手工构造），unit 层完成。
- 扣分推导与 min 合并在引擎层单独测（见 tasks V7.5-004 / V7.5-010）。
