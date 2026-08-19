# DB-04 memory_repository

| 字段 | 内容 |
|---|---|
| Task ID | DB-04 |
| Task Name | memory_repository（长期记忆仓储） |
| Type | DB |
| Priority | P0 |

## Description

实现 `app/repositories/memory_repository.py`，封装 `memories` 表读写。为未来 Vector DB 升级预留：上层只依赖本仓储接口，换存储不换调用方。

## Scope

- `create_memory(user_id, memory, memory_type, importance) -> UserMemory`
- `list_by_user(user_id, limit) -> list[UserMemory]`
- `get_memory(memory_id) -> UserMemory | None`
- `delete_memory(memory_id)`
- `exists_similar(memory, threshold=1.0) -> bool`：V1 用内容完全一致/包含判断去重（阈值预留，语义相似去重为 P1/P2）

## Out of Scope

- 提取判断（BE-09 extractor_chain）
- 检索打分（BE-10 memory_service）
- 向量化 / embedding（P2）

## Dependencies

- DB-01（engine / ORM Model / Session）
- BE-03（UserMemory / MemoryType DTO）

## Input

- `app/core/db.py`（Memory ORM Model）
- `docs/v1/v1-architecture.md` §5 表设计、§9 复用说明

## Output

- `app/repositories/memory_repository.py`

## Business Rules

1. `memory_type` 仅限五类枚举，非法值拒绝。
2. `importance` 范围 0.0~1.0，越界拒绝。
3. `id` 使用 UUID 字符串生成。
4. `exists_similar` 默认做内容去重（全等或子串包含），返回 True 表示已存在。
5. 仓储接口签名稳定：不暴露 SQL 细节，为向量检索替换留缝。

## API Dependencies

- 无

## Data Dependencies

- `memories` 表（DB-01）

## Permission

- 无鉴权要求。

## Error Handling

- 非法 `memory_type` / `importance`：抛 `ValueError`。
- 未找到返回 `None`，不抛异常。
- DB 异常：回滚后抛出。

## Subtask 拆分

- S1：`create_memory` + 校验
- S2：`list_by_user` / `get_memory` / `delete_memory`
- S3：`exists_similar` 去重

## Acceptance Criteria

- 创建记忆后 `get_memory` 可回读，字段一致
- 相同内容两次 `create_memory` 前 `exists_similar` 返回 True
- `list_by_user` 只返回该用户记录
- 非法类型/越界 importance 被拒绝

## Test Requirements

- 内存 SQLite 下：CRUD、按用户隔离、去重、非法值拒绝。
- 测试不依赖真实网络。