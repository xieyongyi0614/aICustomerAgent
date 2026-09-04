# Scene State

## 1. 背景

V2 的 `CharacterState`（能量/心情/关系）描述的是角色的**内在状态**，没有描述**外部场景**。

## 2. 问题

AI 不知道"现在在哪里、正在做什么"，导致每轮回复都在重新即兴发明场景。

## 3. 目标

为每个会话维护一个轻量、有界、可扩展的 SceneState。

## 4. 数据结构

```python
class ActionStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    cancelled = "cancelled"
    superseded = "superseded"   # 被新 Action 取代

class PendingAction(BaseModel):
    action: str
    status: ActionStatus = ActionStatus.pending
    created_at_turn: int = 0

class SceneState(BaseModel):
    session_id: str
    turn_id: int = 0
    location: str | None = None          # 例：客厅
    current_activity: str | None = None  # 例：休息
    current_action: str | None = None    # 例：切西瓜
    pending_action: PendingAction | None = None
    scene_mood: str | None = None        # 例：relaxed
```

## 5. 持久 / 临时状态

| 字段 | 类别 | 说明 |
|---|---|---|
| location / current_activity / current_action / pending_action | 持久（落库） | 跨轮生效，session 级单行，**V3 核心状态** |
| scene_mood | 临时 / optional metadata | **不是 V3 核心状态**：仅用于 Prompt 展示与 Debug，每轮由 Updater 附带重判，不落库、不参与任何状态迁移逻辑；V4/V5 将由专门的 Emotion/Mood 系统接管 |

## 6. 流程

- 回答前：`scene_state_loader` 按 session 读一行（无记录/失败 → 默认空状态）。
- 回答后：`scene_state_updater` 后台写回（见 state-update.md）。

## 7. 边界情况

- 首轮对话：全部字段为 None，Prompt 中 scene 段自动省略。
- 状态读取失败：降级为空状态 + trace 记录，不阻塞回答。
- 字段体积约束：每个字段单条短文本（≤ 50 字），状态天然有界，防止膨胀。
- scene_mood 缺失/非法：不影响任何逻辑，仅 Prompt 中省略该行。

## 8. 验收标准

- Alembic 迁移可执行，ORM 与迁移一致（复用 `test_db_migration` 模式）。
- 每字段超长时 Updater 截断。
- V2 的 CharacterState / RelationshipState 完全不受影响。
