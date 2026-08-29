# Persistence

## 1. 持久化边界总表

| 数据 | 存储 | 理由 |
|---|---|---|
| BehaviorPolicy（stage×mood 参数表） | 代码资产 `app/character/asuna/behavior_policy.py` | 角色定义的一部分，随角色版本演进；不是运行期数据 |
| STRATEGY_INSTRUCTIONS / 映射表 | 代码 `behavior_policy.py` / `behavior_engine.py` | 同上；映射规则变更走代码评审 |
| HABIT_LIST | 代码资产 `app/character/asuna/habits.py` | 长期倾向属角色定义；动态养成为 P2 且需审核，不直写 |
| BehaviorStrategy（单轮） | trace + turn_meta，**不建表** | 与 V6 intention 同待遇：单轮决策无跨轮价值，回放看 trace |
| ActionBudget（单轮） | trace + turn_meta，**不建表** | 同上；预算是派生值（mode×stage×mood×策略），可复算 |
| Habit 匹配结果 | trace | 归因用，无独立价值 |
| Activity | scene_state 表（V3 已有） | 复用，零迁移；V6.5 只读 |
| **ConversationMode** | **conversations 表新增 2 列（迁移 0010）** | 会话级状态，跨轮存活，必须持久化 |

结论：V6.5 唯一的数据库变更 = conversations 加 `mode`、`mode_entered_at` 两列。不建新表。

## 2. Migration Proposal（0010_conversation_mode）

> 仅提案，实施在 V6.5-007 任务；本阶段禁止执行任何数据库变更。

```python
# migrations/versions/0010_conversation_mode.py（示意）
def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("mode", sa.String(16), nullable=False,
                  server_default="default"),
    )
    op.add_column(
        "conversations",
        sa.Column("mode_entered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_conversations_mode",
        "conversations",
        "mode IN ('professional', 'default', 'immersive')",
    )

def downgrade() -> None:
    op.drop_constraint("ck_conversations_mode", "conversations")
    op.drop_column("conversations", "mode_entered_at")
    op.drop_column("conversations", "mode")
```

要点：

- `server_default="default"`：存量会话零迁移成本，首轮即有效。
- CheckConstraint 三值，与 `RoleMode.mode` Literal 对齐——mode 枚举扩展（V8+ 若需要）必须同迁移 + 同模型。
- `mode_entered_at` nullable：存量行保持 NULL，stabilize 将 NULL 视作 now（首次写入时补齐），R4 空闲回落对存量行天然不触发。
- ORM 同步：`app/core/db.py::Conversation` 加同名列 + `app/models/conversation.py::ConversationState` 增加 `mode: str = "default"`（runtime 传递用）。

## 3. 运行期数据流（写路径唯一）

```text
读：ensure_conversation（现有）→ 行已在内存 → context_builder 顺带取 mode/mode_entered_at
算：mode_service.stabilize → ModeDecision{effective, write_back: bool}
写：save_turn 事务内，write_back=True 时 UPDATE mode + mode_entered_at=now
```

- 不新增 UPDATE 往返、不新增后台步骤；写失败随 save_turn 现有异常路径（architecture.md §6）。
- `turns_in_candidate` 候选计数是进程内存 dict（key=session_id），**刻意不持久化**：重启归零只是多一两轮观望，为它建表不值。

## 4. trace / turn_meta 契约

```text
trace.record("behavior_engine", ms, ok, strategy=..., base_strategy=..., rules=[...],
             budget_max=..., matched_habits=[id...])
trace.record("mode_stabilize", ms, ok, confirmed=..., candidate=..., effective=..., rule="R2")
turn_meta 新增：
  "behavior": {"strategy": "...", "budget": {...}, "degraded": bool}
  "mode": {"confirmed": "...", "effective": "...", "switched": bool}
```

- turn_meta 已携带 intention/current_goal（V6-008），V6.5 增量两键，前端 Debug 面板消费（V6.5-009 P1）。
- 内部字段（factor、priority、rule_id 明细）只进 trace，不进 turn_meta。

## 5. 数据生命周期与清理

- 无新表 → 无新清理需求。
- conversations.mode 属会话行生命周期（现存会话删除策略不变）。
- trace 中 behavior 字段随既有 trace 保留策略，不单独治理。
