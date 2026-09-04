# V8.5 M3：Evolution Engine（演化引擎）

> 核心模块：信号 → 事件 → 动力学修饰 → 限速 → 同事务落账。全部纯函数、可重放；LLM 无分数修改权（原则 3）。本文同时定义 **Relationship Evaluation 护栏**（V7.5 集成）——它是"变化是否合理"四问的最终答案。

## 1. 定位与流水线

替代 V5 `apply_relationship_v5` 的调用位置（编排仍在 post_process 第 2 步 state_update 内），V5 主干函数保留为 `rel_evolution_enabled=false` 的退化路径：

```text
InteractionSignal（M2）
  → 事件映射（M2 §4）→ RelationshipEventType + magnitude
  → 基础 delta = EVENT_DELTAS[type] × magnitude 系数 + BEHAVIOR_DELTAS[behavior]（V5 既有）
  → 动力学修饰（§3，逐维独立，rel_evolution_enabled 门控）
  → 三级限速（§4，V5 既有，扩 6 维）
  → clamp [0,1] → EvolutionOutcome
  → 同事务：状态写入 + 账本行（impact 记实际生效值）          ← V5"同事务账本"口径不变
  → 顺次移交 M4 里程碑 / M5 冲突 / M6 记忆投递（同锁不同事务边界，见 §5）
```

## 2. EvolutionOutcome（模块间唯一交接物）

```python
class EvolutionOutcome(BaseModel):
    applied_delta: RelationshipDelta      # 实际生效（限速+clamp 后）
    event: RelationshipEvent | None       # 落账行（无事件轮为 None）
    truncated: dict[str, float]           # 被限速截断的量（审计/评估用）
    window: EvidenceWindowSnapshot        # 信号窗快照（重放输入）
    flags: dict[str, bool]                # modifier 触发标记（trace 用）
```

M4/M5/M6/M7/M8 只消费 Outcome 与状态，不重算 delta。

## 3. 动力学修饰器（V8.5 的灵魂，逐维独立、可重放）

修饰器作用于**基础 delta**，顺序固定（可重放性要求），全部纯函数：

| # | 修饰器 | 规则 | 参数 | 动机 |
|---|---|---|---|---|
| D1 | 边际递减 | 证据窗内第 n 次同 kind+quality **正向**信号 → delta × r^(n−1) | rel_repetition_decay=0.7 | 天天说谢谢不会再加信任 |
| D2 | 高值钝化 | 正向 delta × (1 − current²)；familiarity 豁免 | — | 0.9 的信任涨 0.04 ≈ 涨 0.007 |
| D3 | 信任不对称 | trust 负向 × amp | rel_trust_negative_amp=1.5 | 建立要一年，毁掉一句话 |
| D4 | comfort 快通道 | comfort 不参与 D1/D2（伤得快也好得快），仅参与限速 | — | 自在是短期量 |
| D5 | 显著度调制 | delta × (0.5 + salience) | — | 擦肩寒暄与深夜袒露不该等权 |

- **负向不递减、不钝化**（D1/D2 只作用于正向）：伤害不因重复而麻木——威慑语义。
- familiarity 不参与 D2（经历就是经历）但参与 D1（同一件事反复经历，熟悉度增益递减）。
- 修饰后仍过三级限速（§4）——动力学放大不了违规跳变，限速是绝对上限。

示例（用户第 3 次说谢谢，trust 0.60，salience 0.5，praise +0.02×1.0）：
D5 → 0.02×1.0=0.02；D1 → ×0.7²=0.0098；D2 → ×(1−0.36)=0.0063；限速内放行 → **trust +0.006**。V5 同场景为 +0.02——重复客套的增益被压到三分之一。

## 4. 限速扩展（V5 三级原值，覆盖 6 维）

| 层 | 规则 | settings |
|---|---|---|
| 单事件 | 每维绝对值 ≤ 0.17 | rel_max_event_delta（不动） |
| 单轮 | 事件 + behavior 合计每维 ≤ 0.15 | rel_max_turn_delta（不动） |
| 每日 | 当日每维累计正/负各 ≤ 0.30（账本聚合，超出截断仍落账） | rel_max_day_delta（不动） |
| 里程碑 ★ | bonus 每维 ≤ 0.10，**不受单轮/单日上限约束**（罕见一次性事件走独立预算） | rel_milestone_delta_cap |

- 当日聚合口径沿用 `_day_impact_totals`，扩到 6 维；里程碑 bonus 记入里程碑表（不进 events 账本），日聚合不含它——两条预算互不侵蚀。

## 5. 事务与执行边界

- **状态 + 账本：同一事务**（V5 口径不变，`commit_relationship_update` 扩列后沿用）。
- 里程碑 / 冲突 / 快照各自独立小事务（同一把用户写锁内串行）：某个子系统失败不回滚已生效的演化，符合"只降级"契约。
- comfort 均衡回归（relationship-model.md §4）在同事务内随状态写入；无事件轮也执行（账本无行、状态 version 仍 +1——version 语义 = 演化流水线执行次数，非事件数）。

## 6. 重放与回滚的确定性基础

```text
重放(state_0, event_stream) = state_t     对任意截断点成立
```

成立条件（设计保证）：① 修饰器纯函数；② novelty 只依赖证据窗内容，窗口可由账本重建（interaction-analysis.md §3）；③ comfort 回归只依赖 stage/conflict 与轮数（轮数 = version 差）；④ 限速日聚合在账本内。**回滚 = 取关键帧快照 + 其后账本重放**（persistence.md §5），不需要独立快照每个 version。

## 7. Relationship Evaluation（V7.5 集成，评估护栏）

### 7.1 接入方式（V7.5 官方扩展模式）

- `EvaluationDimension` 增 `relationship`；`IssueCode` 增 4 个；`DEFAULT_SEVERITY`、`evaluation_overall_weights_json` 权重表、`evaluation_relationship_enabled` 开关同步。
- 规则 = Rule 子类 + 加入 `evaluation_rules/relationship.py` 的 RULES 列表（subjects=turn），异常隔离既有机制兜底。**不新增 LLM judge**（留白）。

### 7.2 四条规则

| 规则 | 断言 | 级别 |
|---|---|---|
| RelationshipJumpRule | 任意维单轮 \|Δ\| ≤ rel_max_turn_delta（里程碑轮按 cap 放宽） | fail |
| LedgerReconciliationRule | 状态变化 − 账本 impact 之和 − 里程碑 bonus − 冲突结算 = 漂移容差内（comfort 按 drift×轮数容忍，其余维容差 1e-6） | fail |
| RateComplianceRule | 当日每维累计 ≤ rel_max_day_delta（限速兜底验证，防御未来代码绕过） | warn |
| SignalAccountingRule | 每条账本行的 cause 能对应到证据窗信号 / LLM 事件 / replay 来源之一（无因变化检测） | fail |

### 7.3 题设验收（"第一次聊天 trust=1.0 必须被发现"）

- 构造注入：首回合强推 trust 0.35→1.0 → RelationshipJumpRule fail（issue_code=relationship_jump）+ 限速截断实际生效值 ≤0.17；评估报告可查、trace 可关联（V7.5 既有 correlation 链路）。
- 构造注入：直接改状态不落账 → LedgerReconciliationRule fail（relationship_uncaused_change）。

## 8. 验收标准

- 修饰器逐条单测（含示例数值 0.0063 精确断言）；顺序固定性（乱序注入结果不变）。
- 关闭 rel_evolution_enabled → 输出与 V5 路径逐位一致（回归桥测试）。
- 里程碑 bonus 独立预算、不侵单日上限。
- 重放：随机事件流重放 100 次（种子固定）状态终态全等。
- 四条评估规则正反例齐备；evaluate 全链零 LLM 调用。
- 全量既有测试零回归（state_update 步骤语义兼容）。
