# Memory Model

## 1. 背景

V1 已有 `MemoryType = preference/fact/goal/experience/relationship` 五类，粒度不均且与场景/事件语义混杂。

## 2. V4 记忆分类（4 类）

```python
MemoryType = Literal[
    "user_preference",       # 用户长期偏好："用户不喝咖啡""喜欢安静"
    "user_fact",             # 用户客观事实："用户在深圳工作""养了一只猫"
    "important_event",       # 重要事件："用户上周参加了面试"
    "relationship_event",    # 关系事件："用户送过亚丝娜一条围巾""一起看过流星"
]
```

**不再增加其他类型**。理由：
- "目标/goal"可由 user_fact 或 important_event 表达，单独成类会造成提取时归类犹豫。
- 用户情绪/关系亲密度属于 V5（Emotion/Relationship），不提前引入。
- 4 类已覆盖"是什么样的人 / 有什么事实 / 发生过什么 / 我们之间发生过什么"四个正交维度。

**旧类型映射（Alembic 迁移时执行）**：
`preference→user_preference`；`fact/goal→user_fact`；`experience→important_event`；`relationship→relationship_event`。

## 3. Memory Candidate（Extractor 输出）

```python
MemorySource = Literal["user_stated", "user_derived", "ai_inferred"]

MemoryAction = Literal["save", "update", "invalidate", "forget", "suppress", "none"]

class MemoryCandidate(BaseModel):
    action: MemoryAction = "none"        # 见 memory-conflict.md / privacy.md
    type: MemoryType
    content: str | None = None           # 精简、去语境陈述句
    importance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)   # 提取置信度
    source: MemorySource = "ai_inferred" # 信息来源
    target_memory_id: str | None = None  # action=update/invalidate 时必填
```

`source` 语义：
- `user_stated`：用户原话直接表达（"我不喝咖啡了"）。
- `user_derived`：从用户多轮表述中可直接推导、无脑补（用户说"我家猫总挠沙发" → 用户养猫）。
- `ai_inferred`：模型推测的用户心理/状态（"你一定很开心"）→ **Policy 硬丢弃**。

## 4. Memory Repository 数据模型（memories 表扩展）

```python
class Memory(Base):           # core/db.py 现有表扩展
    id: str                   # PK, uuid
    user_id: str              # 索引
    character_id: str         # 新增，默认 "asuna"，索引
    type: str                 # 原 memory_type 重命名，V4 4 类
    content: str              # 原 memory 重命名
    importance: float
    confidence: float         # 新增
    source: str               # 新增
    status: str               # 新增：active / superseded / invalidated
    superseded_by: str | None # 新增：指向替代记忆 id
    created_at / updated_at: datetime
    last_accessed_at: datetime | None  # 新增，召回时更新
    expires_at: datetime | None        # 新增，一次性/临时信息用（默认 None）
```

## 5. 绑定层级决策

**推荐：绑定 user + character，不绑 session / conversation。**

| 选项 | 判断 | 理由 |
|---|---|---|
| session | ❌ | 会话结束记忆即失效，无法跨会话，违背 V4 目标 |
| conversation | ❌ | 同上，且 conversation 是窗口消息容器，生命周期短 |
| user only（V1 现状） | ⚠️ | 跨会话但跨角色串味：换人设后"用户不喝咖啡"仍适用，但"用户送过围巾"不该出现在别人设里 |
| **user + character** | ✅ | 用户级事实（深圳工作）随 user 走；角色级关系事件随 (user, character) 走。实现折中：全部行带 character_id，user 级通用事实提取时标记 `character_id="*"`，召回时 `character_id IN (当前角色, '*')` |

## 6. 验收标准

- 类型校验非法值被拒（沿用 VALID_MEMORY_TYPES 模式）。
- 旧数据迁移后可按新类型检索。
- (user, character, status=active) 索引查询 < 10ms（当前规模）。
