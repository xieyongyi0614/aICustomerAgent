# DB-01 三张状态表与存取层

| 字段 | 内容 |
|---|---|
| Task ID | DB-01 |
| Task Name | 状态三表 ORM 与三个 repository |
| Type | DB |
| Priority | P0 |

## Description

在 `app/core/db.py` 追加 `character_state` / `relationship_state` / `emotion_history` 三张表的 ORM 行模型，并新建三个 repository，对上层提供"永远有状态"的读取语义。lifespan `create_all` 只增不改，V1 四张表零影响。

## Scope

- ORM：`CharacterStateRow`、`RelationshipStateRow`、`EmotionHistoryRow`（DDL 见架构文档 §5）
- `app/repositories/character_state_repository.py`：
  - `get_state(user_id) -> CharacterState`（未命中返回默认实例，**不写库**，`updated_at` 填行值）
  - `upsert_state(user_id, state)`（存在则 update，不存在则 insert，维护 `updated_at`）
- `app/repositories/relationship_repository.py`：`get_relationship(user_id)` / `upsert_relationship(user_id, rel)` 同构
- `app/repositories/emotion_history_repository.py`：
  - `append(user_id, session_id, user_emotion, event, behavior, mood_before, mood_after, energy_after, stage_after)`
  - `list_recent(user_id, limit)`（按 `created_at` 倒序）

## Out of Scope

- 状态更新规则与调用时机（BE-02 / BE-07）
- 闲置恢复计算（BE-02，repo 只提供原始 `updated_at`）

## Dependencies

- BE-01（DTO 类型）

## Input

- `docs/v2/v2-architecture.md` §5 数据库设计（含 CheckConstraint 枚举与索引定义）
- V1 仓储风格参照：`app/repositories/memory_repository.py`

## Output

- `app/core/db.py`（修改，追加三个 ORM 行模型）
- `app/repositories/character_state_repository.py`、`app/repositories/relationship_repository.py`、`app/repositories/emotion_history_repository.py`
- `tests/test_state_repositories.py`

## Business Rules

1. 一对一状态表以 `user_id` 为 PRIMARY KEY，upsert 语义天然成立（先例：V1 `conversation_summaries`）。
2. `get_state` / `get_relationship` 未命中返回 BE-01 默认值（calm / 0.9 / friend），绝不因缺行抛错——上层永远拿到可用状态。
3. `emotion_history` 只追加不更新不删除；每轮一行，含降级轮。
4. 保持 V1 风格：模块级函数 + 每次调用独立 `SessionLocal` 短会话。
5. CheckConstraint 枚举、索引 `(user_id, created_at)`、时间戳 `datetime.now()` 均对齐 V1 惯例。

## API Dependencies

- 无

## Data Dependencies

- SQLite（内存 SQLite 用于测试）

## Permission

- 无

## Error Handling

- DB 异常：回滚后向上抛，由调用方（BE-07 的 try/except）兜底。
- 非法枚举 / 越界浮点：靠 CheckConstraint 与 DTO 校验双重拦截。

## Subtask 拆分

- S1：三个 ORM 行模型 + 建表验证
- S2：`character_state_repository`（get 默认值 + upsert）
- S3：`relationship_repository`
- S4：`emotion_history_repository`（append + 倒序查询）
- S5：单测

## Acceptance Criteria

- 内存 SQLite `create_all` 后三表存在，V1 四表结构不变
- get 未命中返回默认值且库里无行
- 同一 user 两次 `upsert_state` 后仍一行、字段为第二次值、`updated_at` 前进
- history 追加两条后 `list_recent` 倒序返回

## Test Requirements

- `tests/test_state_repositories.py`：默认值、upsert 幂等、updated_at 前进、倒序、跨 user 隔离
- monkeypatch 替换三个 repository 模块的 `SessionLocal`（复用 V1 conftest 模式）
