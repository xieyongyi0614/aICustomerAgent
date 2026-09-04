# Relationship Model

## 1. 背景

V2 已有 intimacy/trust/familiarity 三维 [0,1] + stage，缺 tension。

## 2. 维度设计（4 维，第一版封顶）

```python
class RelationshipState(BaseModel):     # 扩展现有模型
    intimacy: float = 0.3        # 沿用 V2：亲密
    trust: float = 0.35          # 沿用 V2：信任
    familiarity: float = 0.3     # 沿用 V2：熟悉
    tension: float = 0.0         # ★新增：紧张/隔阂 0.0 起
    stage: RelationshipStage = "friend"
    updated_at: datetime | None = None
```

- **不采纳题设 closeness 命名**：V2 已有 intimacy 表达同一概念，重命名徒增迁移成本，文档记录映射 closeness ≡ intimacy。
- tension 特性：**可双向变化且可被关系修复消解**——正向互动（comforted/warm_moment）按小比例消耗 tension（-0.02 每次命中），冲突/批评抬高它。
- tension 影响 Prompt 表达（"最近有点尴尬"）并抑制 stage 判定（tension > 0.5 时 stage 冻结升级，见 relationship-stage.md）。

## 3. 什么事件改变关系（delta 表 = 唯一变化来源）

沿用 V2 `EVENT_DELTAS`/`BEHAVIOR_DELTAS` 并扩充（magnitude 系数同情绪：weak 0.6 / normal 1.0 / strong 1.4）：

| 事件类型 | trust | intimacy | familiarity | tension |
|---|---|---|---|---|
| user_care（主动关心/安慰） | +0.04 | +0.03 | +0.01 | -0.02 |
| user_help（帮助角色） | +0.05 | +0.03 | +0.02 | — |
| long_interaction（长时间共同互动=daily 累计） | — | +0.01 | +0.02 | — |
| intimate_moment（亲密互动） | +0.02 | +0.06 | +0.01 | -0.01 |
| praise / warm_moment | +0.02 | +0.02 | +0.01 | -0.01 |
| criticized / complaint | -0.03 | — | — | +0.05 |
| conflict / 争吵 | -0.10 | -0.12 | -0.05 | +0.20 |
| boundary_violation（越界行为） | -0.08 | -0.05 | — | +0.15 |

- 表中数值即**单事件上限**（magnitude strong 时最高 ×1.4，见 relationship-update.md 上限）。
- 事件类型到该表的映射由代码持有；LLM 只输出 RelationshipEventType + 档位（relationship-events.md）。

## 4. 事件类型（检测器输出，扩展 TurnAnalysis）

```python
RelationshipEventType = Literal[
    "user_care", "user_help", "intimate_moment", "long_interaction",
    "praise", "criticized", "conflict", "boundary_violation", "none",
]
```

- 与 V2 `EventCategory`（achievement/setback/...）并存过渡：V2 分类映射到 V5 类型（achievement→praise、complaint→criticized、conflict→conflict、share_goal/seek_help→user_help、daily→none[累计计 familiarity]）。

## 5. 验收标准

- tension 默认 0.0、参与 clamp 与 stage 冻结。
- 旧数据迁移：tension 补 0.0，其余维度保留。
- delta 表数值全部走 settings 或常量表，无硬编码散落。
