# V8.5 M4：Milestone System（里程碑系统）

> 关系编年史：把"第一次"与"阶段跃迁"从匿名事件行升格为可查询、可奖励、可解锁、可入记忆的一等实体。

## 1. 为什么需要里程碑

- stage 跃迁有滞回与冻结，是"统计结果"不是"仪式"——第一次袒露心事这种时刻值得被单独记住。
- 里程碑是行为与自主系统天然的**权限载体**（"确认过关系够深才解锁的主动行为"），比裸阈值更可解释、可审计。
- 里程碑是记忆投递的重要来源（memory-integration.md）与 Prompt 的关系上下文素材（behavior-integration.md）。

## 2. 模型与注册表

```python
@dataclass(frozen=True)
class MilestoneSpec:
    key: str                                  # first_self_disclosure ...
    title: str                                # Prompt/展示用（角色资产）
    detect: Callable[MilestoneContext, bool]  # 纯函数谓词
    bonus: RelationshipDelta                  # 一次性奖励（受 rel_milestone_delta_cap=0.10 限速）
    memory_worthy: bool                       # 是否投递长期记忆
    unlocks: tuple[str, ...]                  # 解锁权限 key（M7/M8 消费）

MILESTONES: list[MilestoneSpec] = [...]       # 注册表，模式同 V7.5 RULES
```

存储表 `relationship_milestones`（结构见 persistence.md §2）：`UniqueConstraint(user_id, milestone_key, period_key)` 保证幂等——重复检测天然跳过（评估 MilestoneRule 的 duplicate 断言兜底）。

## 3. 首发目录（12 项）

| key | 谓词 | bonus | memory | unlocks |
|---|---|---|---|---|
| first_interaction | 账本首行产生 | familiarity +0.02 | ✗ | — |
| first_self_disclosure | self_disclosure 事件升格 | trust +0.03, intimacy +0.02 | ✓ | emotional_support_deep |
| first_support_in_distress | support 事件 × 角色情绪 intensity>0.6 负面 | trust +0.04, intimacy +0.02, comfort +0.03 | ✓ | — |
| first_promise_kept | promise_kept 事件 | trust +0.04 | ✓ | — |
| first_shared_activity | shared_activity 事件 | familiarity +0.03, comfort +0.02 | ✓ | — |
| first_conflict | conflict 事件 | 无（负向走事件 delta） | ✓ | conflict_recovery_available |
| first_apology | recovery 迁移发生（M5） | comfort +0.03 | ✓ | — |
| first_forgiveness | resolved(reconciled) 迁移（M5） | trust +0.02, comfort +0.05 | ✓ | — |
| stage_friend / stage_close_friend / stage_partner | stage 跃迁刻印 | 无 | ✓ | 见 §5 |
| monthly_anniversary | 认识满 N 月（period_key=YYYY-MM） | comfort +0.02 | ✗ | — |

- first_support_in_distress 依赖情绪语境——这是"Emotion 不改关系分数"原则的合规用法：情绪只做**信号显著性/谓词上下文**，不直接产生 delta。
- 负向里程碑（first_conflict）无 bonus：里程碑记录事实，不补偿伤害。

## 4. 检测流程（state_update 步骤内，演化之后）

```text
EvolutionOutcome + 状态 + 账本近况 + 情绪语境
  → 逐 spec 谓词（已存在的 key 跳过，一条 SQL 预载已有集合）
  → 命中：写 milestones 行（含 applied_bonus）→ bonus 应用（独立 cap）
        → memory_worthy → 记忆候选（M6）
        → unlock key 生效（消费方查询 milestones 表即得，无独立状态）
  → 各自独立小事务；检测异常跳过当轮（幂等，下轮补检）
```

- 命中顺序即注册表顺序；一轮多命中全部记录（bonus 逐个过 cap）。
- 阶段跃迁刻印与 V5 next_stage 同步发生（同轮检测），不需要额外触发器。

## 5. 解锁权限（unlocks 语义表）

权限 key 只是**门牌**，语义由消费方定义：

| key | 定义 | 消费方 |
|---|---|---|
| emotional_support_deep | 允许在 Prompt 中提"TA 曾对我袒露过脆弱的一面"类上下文 | M7 |
| conflict_recovery_available | 允许 reconciliation_check_in 主动意图 | M8 |
| casual_check_in（stage_friend） | 日常寒暄类主动消息解锁 | M8 |
| proactive_goodnight（stage_close_friend） | 晚安/关怀类主动消息解锁 | M8 |
| personal_topics（stage_close_friend） | 主动提起私人话题 | M8 |
| deep_commitment_language（stage_partner） | 深层承诺语言档 | M7 |

- 解锁查询 = `EXISTS(milestones WHERE key=…)`，无缓存无状态——简单可审计。
- 权限只增不减（关系倒退不回收已解锁项；倒退的克制由 M8 R1/R2 冲突与 comfort 门控负责）。

## 6. 验收标准

- 目录 12 项谓词正反例；unique 幂等（重复注入零重复行）。
- bonus 独立 cap（>0.10 注入被截断）；bonus 不进 events 账本、不侵单日预算。
- 阶段跃迁刻印与 next_stage 同轮一致；anniversary period_key 逐月独立。
- 解锁查询与评估 duplicate 规则联动正确。
- 检测异常注入：回合不阻塞，下轮补检成功。
