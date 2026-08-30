# V8.5 M1：Relationship Model（关系状态模型）

> V5 已有 4 维 + stage；本文定义 V8.5 的 5+1 维模型、每维语义与变化规则、派生指标，并冻结阶段体系。

## 1. 维度模型（5 + 1）

```python
class RelationshipState(BaseModel):      # 扩展 V5 模型
    intimacy:    float = 0.30   # 沿用 V5：亲密（题设 affection ≡ intimacy，沿用既有列名不迁移）
    trust:       float = 0.35   # 沿用 V5：信任
    familiarity: float = 0.30   # 沿用 V5：熟悉
    respect:     float = 0.60   # ★新增：尊重
    comfort:     float = 0.60   # ★新增：自在
    tension:     float = 0.00   # 沿用 V5：紧张（负向轴）
    stage: RelationshipStage = "friend"          # 四级冻结，见 §5
    conflict_status: str = "none"                # ★冗余当前冲突态（M5 维护）
    neglect_active: bool = False                 # ★疏远标记（M5 维护）
    last_interaction_at: datetime | None = None  # ★neglect/时间演化用
    version: int = 0                             # ★单调递增，见 persistence.md
```

默认值与默认 stage=friend 自洽：朋友之间 respect 0.60（基本认可）、comfort 0.60（相处还算自在）。**新维度默认值落在"不渲染"档**，是"默认态 golden 不变"（behavior-integration.md §3）的前提之一。

## 2. 维度语义表（含义 / 范围 / 变化特性）

| 维度 | 含义 | 范围/默认 | 变化速度 | 不对称性 | 均衡点 |
|---|---|---|---|---|---|
| intimacy 亲密 | 情感联结强度 | [0,1] / 0.30 | 慢升中降 | 正负都较敏感 | 无（停在当前位置） |
| trust 信任 | 可靠性与安全感 | [0,1] / 0.35 | 慢升**快降** | 负向 ×1.5（rel_trust_negative_amp） | 无 |
| familiarity 熟悉 | 共同经历的数量与广度 | [0,1] / 0.30 | 单调缓升 | 几乎不降（时间不倒退） | 无 |
| respect 尊重 | 对能力/判断/边界的认可 | [0,1] / 0.60 | 慢升快降 | 对 boundary_violation 最敏感 | 无 |
| comfort 自在 | 相处时的当下轻松感 | [0,1] / 0.60 | **双向快变** | 伤得快、也好得快 | 阶段基线（见 §4） |
| tension 紧张（V5） | 摩擦与隔阂的累积（负向轴） | [0,1] / 0.00 | 累积慢、消解慢 | 正向互动可消耗（V5 规则） | 0 |

与其他概念的分界：

- **comfort ≠ tension 的反义**：tension 是"积压的摩擦"（事件累积、慢性），comfort 是"当下的自在"（快变、向基线回归）。冷战期可以 tension 高、comfort 极低；一次尴尬冷场拉低 comfort 但不产生 tension。
- **comfort ≠ Emotion**：emotion 是角色的心情（任何来源），comfort 专指"和这个用户相处"的关系性自在。
- **respect ≠ trust**：信任是"TA 不会辜负我"，尊重是"TA 值得我另眼相看"。可以信任一个无能的老友（trust 高 respect 低），也可以尊重一个尚不亲近的能人（respect 高 trust 低）。

## 3. 变化规则：delta 表扩容（唯一变化来源）

V5 的 `RELATIONSHIP_EVENT_DELTAS`（constants.py）扩到 6 列；事件类型 9→11（新增 promise_kept / promise_broken，详见 interaction-analysis.md §4）：

| 事件类型 | trust | intimacy | familiarity | respect | comfort | tension |
|---|---|---|---|---|---|---|
| user_care | +0.04 | +0.03 | +0.01 | +0.01 | +0.03 | −0.02 |
| user_help | +0.05 | +0.03 | +0.02 | +0.03 | +0.02 | — |
| long_interaction | — | +0.01 | +0.02 | — | +0.01 | — |
| intimate_moment | +0.02 | +0.06 | +0.01 | — | +0.04 | −0.01 |
| praise | +0.02 | +0.02 | +0.01 | +0.01 | +0.01 | −0.01 |
| warm_moment | +0.02 | +0.02 | +0.01 | — | +0.03 | −0.01 |
| criticized | −0.03 | — | — | −0.02 | −0.03 | +0.05 |
| conflict | −0.10 | −0.12 | −0.05 | −0.05 | −0.12 | +0.20 |
| boundary_violation | −0.08 | −0.05 | — | −0.10 | −0.10 | +0.15 |
| promise_kept ★ | +0.05 | +0.01 | +0.01 | +0.02 | +0.02 | — |
| promise_broken ★ | −0.12 | −0.04 | — | −0.08 | −0.08 | +0.10 |
| none | — | — | — | — | — | — |

`BEHAVIOR_DELTAS` 同步补 comfort 列：comfort +0.02 / celebrate +0.02 / encourage +0.01 / recall_memory +0.01。

- 表值即**单事件上限**（V5 口径）；magnitude 系数 weak 0.6 / normal 1.0 / strong 1.4 不变。
- 数值全部进常量表，无硬编码散落（V5 验收标准重申）。

## 4. comfort 均衡回归（唯一带均衡点的维度）

自在感会向"这个阶段该有的自在度"缓慢回归——久处不厌的默契是阶段属性，不是单次互动属性：

```text
baseline(stranger)=0.45  baseline(friend)=0.60
baseline(close_friend)=0.70  baseline(partner)=0.80    # rel_comfort_baseline_json
每轮（state_update 内，无信号也执行）：
  comfort += (baseline(stage, conflict 修正) − comfort) × rel_comfort_drift(0.05)
conflict 修正：active conflict 期 baseline −0.10（冷战期"怎么都自在不起来"）
```

- 回归量**不计入限速与账本事件**，但计入"因"白名单（显式漂移，评估对账时按轮数容忍，见 evolution-engine.md §6）。
- 其余维度一律无均衡回归：不在一起了信任不会自己蒸发——时间的影响只通过 neglect 信号显式产生（conflict-system.md §4），可审计。

## 5. 阶段体系：冻结不动

V5 结论重申并扩展为 V8.5 硬约束：

- 四级 `stranger / friend / close_friend / partner`、升级全维达阈值、降级迟滞 0.10、每轮最多一级、`tension > 0.5` 冻结升级——**全部原样**。
- **respect / comfort 不参与 stage 阈值判定**（P0 兼容不变量）。它们通过三间接通道影响"阶段感"：信号映射（尊重崩塌伴随信任事件）、行为修饰（respect 低 → 语气克制，behavior-integration.md §4）、里程碑刻印（阶段跃迁本身是里程碑）。
- 阶段阈值调参属未来调优任务，任何调整需更新回归基线并全量回归。

## 6. 派生指标（纯函数计算，不落库）

```python
def distance_index(state, now) -> float:
    """疏离度 0~1：主动行为克制门控（M8 R2/R5）与 prompt 距离档使用。"""
    recency_days = (now - state.last_interaction_at).days  # 无记录按 neglect 阈值封顶
    recency_penalty = min(recency_days / rel_neglect_days_json[state.stage], 1.0)
    return clamp01(0.5 * state.tension + 0.3 * (1 - state.comfort) + 0.2 * recency_penalty)
```

- 亲近度等展示型聚合不做（避免多口径）：Prompt 用档位文案（§7），门控用单指标 distance_index。
- 派生指标不落库、不进账本、不触发事件——它们是状态函数，任何时刻可重算。

## 7. 档位文案（Prompt 呈现基础，M7 消费）

沿用 `describe_level` 三档模式，新增两维档位表（角色资产）：

| 维度 | 低 (<0.4) | 中 (0.4~0.7) | 高 (>0.7) |
|---|---|---|---|
| respect | 言行让你有些失望 | 保持应有的尊重 | 由衷敬佩 |
| comfort | 相处有些放不开 | 相处还算自在 | 相处毫无负担 |

## 8. 验收标准

- 新维度默认值 / clamp [0,1] / server_default 旧行兼容；旧四维行为逐位不变（V5 既有测试零改动通过）。
- delta 表 6 列与 magnitude 系数联动正确；promise_kept/broken 两新类型落账。
- comfort 均衡回归：无信号轮也执行、conflict 期基线下调、回归量不计限速。
- stage 判定对新维度完全不敏感（把 respect/comfort 打满，stage 迁移路径与 V5 一致）。
- distance_index 边界：tension=0/comfort=1/刚互动 → 0；全反 → 1。
