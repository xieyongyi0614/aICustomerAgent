# LLM Judge

> Judge 链（app/chains/evaluation_judge_chain.py + app/prompts/evaluation_judge.py，新增）：规则判不了的语义判定交给 LLM。**禁止自由评价**——输出必须是 Pydantic 强 schema，evidence 必须自证。沿用 `build_structured_output` 既有范式（主链 + 一层降级）。

## 1. 何时用 judge

judge 只回答规则无法确证的三类问题：

1. **像不像**——语气 / 价值观 / 知识边界（persona）；
2. **过不过**——情绪强度与转向是否过度（emotion）；
3. **真不真**——被引述的用户事实有没有支撑（memory 定罪）、主动消息有没有必要（autonomy）。

可数的全部留在规则层（见 rule-engine.md §1）。判定顺序：规则先行 → judge 后行 → min 合并，judge 永远不看到规则的判定结果（避免锚定，两个判定器独立出错才有多样性价值）。

## 2. 合并单调用（关键决策）

一次评估**只发一次 judge 调用**，一个 prompt 同时产出 persona / emotion / memory 三维子判定：

```python
class TurnJudgeResult(BaseModel):
    persona: PersonaJudgement | None
    emotion: EmotionJudgement | None
    memory: MemoryJudgement | None

class ProactiveJudgeResult(BaseModel):      # 主动主体变体
    autonomy: AutonomyJudgement
    persona: PersonaJudgement
```

**被否方案**：每维独立调用。三倍 token 成本与三次延迟叠加，且三维输入高度重叠（reply + digest）——独立调用的收益只有故障隔离，而该收益用"子结果可空 + 整体降级"即可获得。

子结果可空：单维解析失败（如某子字段缺省）不拖垮整体，缺席维度照常缺席。

## 3. Schema 设计（反自由评价的三道闸）

```python
class PersonaIssueCode(StrEnum):  PERSONA_OOC / PERSONA_KNOWLEDGE_LEAK
class EmotionIssueCode(StrEnum):  EMOTION_OVERSHIFT / EMOTION_TEXT_STATE_CONFLICT
class MemoryIssueCode(StrEnum):   MEMORY_FABRICATION / MEMORY_CONTRADICTION / MEMORY_MISSED
class AutonomyIssueCode(StrEnum): AUTONOMY_UNNECESSARY / AUTONOMY_REDUNDANT

class PersonaJudgement(BaseModel):
    in_character: bool
    score: float            # Field(ge=0, le=1)
    codes: list[PersonaIssueCode]
    evidence_quote: str = ""   # ≤80 字符
    confidence: float        # Field(ge=0, le=1)
# Emotion / Memory / Autonomy 同构；MemoryJudgement 另有受限引用 memory_ids: list[int]
```

1. **code 受限枚举**：judge 只能从预定义编码中选，message 由服务端按 code 模板生成——LLM 没有自由撰写的通道。
2. **evidence 自证闸**：`model_validator` 校验 `evidence_quote in reply`；不是子串 → 清空 evidence 且该 issue 降级为无证据 issue（severity 降 info）。judge 必须指着原文说话。
3. **受限引用闸**：memory_ids 只能取 digest 注入的 id 集合，越界引用整体丢弃。

数值出界（score > 1 等）由 schema 校验拒绝，走降级链重解析一次，仍失败则该子结果为 None。

## 4. Prompt 结构

```text
system（固定，随代码走）：
  你是角色扮演质量评审。基于给定上下文摘要与评审标准，输出结构化判定。
  评分基准：1.0 完全在角色内且自然 …… 0.0 严重违和。拿不准时向中间收敛。
  只能引用 reply 原文作为 evidence。

user（每次组装）：
  【评审标准】按维固定条文（persona 三条 / emotion 两条 / memory 两条，
              与各维文档 §judge 层的评审标准一字对应）
  【角色基准】identity / personality 摘录 + 当前 stage / mode / relationship
  【上下文摘要】context digest（user_message / reply / recent_messages /
              injected_memories / emotion / proactive?）
```

prompt 组装走独立模板文件 `app/prompts/evaluation_judge.py`；角色基准直接引用 `character/<persona>/` 资产常量——**评审宪法与生成宪法同源**。

## 5. 调用与降级

```text
judge_llm = get_llm(evaluation_judge_profile or None)
        # 签名 get_llm(profile_id: str | None = None)；None = default profile
chain = build_structured_chain(messages, TurnJudgeResult, judge_llm)
        # 主链 with_structured_output → 降级链 PydanticOutputParser 解析，一层，无循环重试
异常 / 校验失败 → 返回 None
  → 引擎侧：报告只含规则结果，trace.evaluation = degraded
```

- judge 实例**不复用** ctx.llm（那是对话 profile 的实例）：配置了独立 `evaluation_judge_profile` 时经 `llm_factory.get_llm` 另取；测试经 `core/llm_factory.set_llm` 注入 FakeLLM 同样生效（与全库测试约定一致）。

- judge 用独立 profile 配置（`evaluation_judge_profile`）——评审模型可与对话模型不同档位，默认跟随 default。
- **成本控制**：`evaluation_llm_judge_sample_rate` 按 `request_id` 前缀确定性哈希采样（同轮重放结果一致，测试可固定）；0.0 = 纯规则模式，behavior 维不受影响。
- judge 调用发生在**写锁外的后台任务**内（采样命中时由 post_process 第 7 步派发）：与聊天关键路径零竞争，也不延长 per-user 写锁持有（architecture.md §3 写锁两阶段）。

## 6. 独立判定的代价与接受理由

规则与 judge 互不可见 → 可能结论冲突（规则报 CANDIDATE、judge 判无支撑）。冲突的处理是**编码表层面预先定义**（如 CANDIDATE + FABRICATION 同现 → 吸收为 critical；judge 缺席 → CANDIDATE 单独生效），而不是运行时协商——冲突解决是合并器的确定性职责，见 evaluation-model.md 与各维文档。
