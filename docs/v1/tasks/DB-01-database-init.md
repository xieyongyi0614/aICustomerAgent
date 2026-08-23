# DB-01 SQLite 引擎与 ORM 建表

| 字段 | 内容 |
|---|---|
| Task ID | DB-01 |
| Task Name | SQLite 引擎与 ORM 建表 |
| Type | DB |
| Priority | P0 |

## Description

建立 SQLAlchemy 2.0 引擎与会话管理（`app/core/db.py`），按 `docs/v1/v1-architecture.md` §5 创建 4 张表：`conversations`、`messages`、`conversation_summaries`、`memories`。支持文件型 SQLite（生产/本地）与内存 SQLite（测试）。

## Scope

- `app/core/db.py`：engine 创建、Session 工厂、Base（DeclarativeBase）、统一建表入口 `create_tables()`
- ORM Model 定义：`Conversation`、`Message`、`ConversationSummary`、`Memory`
- 表结构、约束、索引按架构文档 §5 原文
- 测试用内存库支持（`sqlite:///:memory:`）
- `.env` 支持 `DATABASE_URL` 配置（默认 `sqlite:///./asuna.db`）

## Out of Scope

- Repository 层 CRUD 方法（DB-02 / DB-03 / DB-04）
- 业务层使用（BE-07 等）
- 任何业务字段之外的扩展字段

## Dependencies

- ARCH-01（目录结构）

## Input

- `docs/v1/v1-architecture.md` §5 数据库设计
- `app/core/` 空壳目录（来自 ARCH-01）

## Output

- `app/core/db.py`
- `app/models/` 或 `app/core/db.py` 内 ORM Model（建议集中放在 `app/core/db.py`，Model 类名与表名映射见 Business Rules）
- 依赖项：`sqlalchemy` 加入 `pyproject.toml`（如缺失）

## Business Rules

1. 表结构 / 约束 / 索引必须与架构文档 §5 完全一致（含 `CHECK(role IN ('human','ai'))`、`memories` 类型枚举 CHECK、`idx_messages_conv`、`idx_memories_user`）。
2. `conversation_id` 与 `user_id` 均为字符串；`id` 用 UUID 字符串。
3. 建表幂等：`Base.metadata.create_all(engine)`，可重复调用。
4. `get_session()` 提供上下文管理器，异常时回滚并关闭。
5. 内存库仅测试使用，生产默认文件库。

## API Dependencies

- 无

## Data Dependencies

- 无（本 Task 即数据层起点）

## Permission

- 无鉴权要求。

## Error Handling

- 引擎连接失败：启动时即报错，配置错误信息含 `DATABASE_URL`（不打印密码等敏感项）。
- 会话异常：上下文管理器统一 `rollback()` 后重新抛出。

## Subtask 拆分

- S1：添加 `sqlalchemy` 依赖到 `pyproject.toml`
- S2：`app/core/db.py` 实现 engine / Base / Session 工厂 / `create_tables()`
- S3：定义 4 张表 ORM Model
- S4：`settings.py` 预留 `DATABASE_URL` 读取（BE-01 提供后接入）
- S5：导入冒烟验证建表成功

## Acceptance Criteria

- `create_tables()` 在文件库与内存库均执行成功
- `sqlite3` 打开生成的库文件，4 张表存在且字段/索引与设计一致
- 违反 `CHECK(role...)` 约束插入会被拒绝
- 内存库多次调用 `create_tables()` 不报错（幂等）

## Test Requirements

- 本 Task 由 TEST-01 的 conftest 使用内存库 fixture 验证；此处以手动冒烟为准。
- 提交一个最小用例：创建内存库 → 建表 → 插入一条 Message → 查询返回。