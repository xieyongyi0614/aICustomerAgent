# ARCH-01 三层目录落地与旧模块迁移

| 字段 | 内容 |
|---|---|
| Task ID | ARCH-01 |
| Task Name | 三层目录落地与旧模块迁移 |
| Type | ARCH |
| Priority | P0 |

## Description

按 `docs/version/v1.0.0/v1/v1-architecture.md` §4 建立三层目录结构（`api/` 表现层、`services/` 业务层、`repositories/` 数据层，外加 `core/`、`models/`、`prompts/`、`character/`、`chains/` 支撑层），并将旧 `app/modules/llm/` 中代码迁移到新位置。本 Task 只做结构调整与空壳落地，不实现业务逻辑。

## Scope

- 创建新目录与 `__init__.py`：`app/core/`、`app/services/`、`app/repositories/`、`app/chains/`、`app/models/`、`app/prompts/`、`app/character/`
- 迁移 `RoleMode` 至 `app/models/router.py`
- 迁移 `role_router_prompt` 至 `app/prompts/router.py`
- 迁移角色人设至 `app/character/asuna/`（identity / personality / relationship / behavior / modes 五个文件）
- 删除旧 `app/modules/llm/` 全部文件
- 删除遗留文件 `app/api/__init__ copy.py`
- 各新目录仅放 `__init__.py` 与空占位（具体实现由后续 Task 填充）

## Out of Scope

- 任何业务逻辑实现（由 BE-01 至 BE-14 完成）
- 数据库建表（DB-01）
- 迁移内容的具体改写与拆分设计细节（BE-04）

## Dependencies

- 无（首个 Task）

## Input

- `apps/backend/app/modules/llm/config.py`（ASUNA_CORE / MODE_INSTRUCTIONS / role_router_prompt / build_asuna_system_message）
- `apps/backend/app/modules/llm/models.py`（RoleMode）
- `apps/backend/app/api/__init__ copy.py`（遗留文件）

## Output

- 新三层目录结构（空壳）
- `app/models/router.py`（RoleMode 原样迁移）
- `app/prompts/router.py`（role_router_prompt 原样迁移）
- `app/character/asuna/*.py`（人设内容按文件拆分）
- 旧 `modules/llm/` 删除、`__init__ copy.py` 删除

## Business Rules

1. 依赖方向单向：`api → services → repositories → core`；`models/prompts/character/chains` 为共享层，禁止反向引用。
2. `app/character/` 按角色分子目录（如 `asuna/`）；`asuna/` 五文件内容划分：`identity.py`=ASUNA_CORE 核心人格段；`personality.py`=人格细化；`relationship.py`=用户身份关系段；`behavior.py`=行为原则段；`modes.py`=MODE_INSTRUCTIONS。
3. 迁移时保留原文内容与格式，语义不得改变。

## API Dependencies

- 无

## Data Dependencies

- 无

## Permission

- 无鉴权要求。纯内部代码组织任务。

## Error Handling

- 迁移后运行 `python -c "from app.models.router import RoleMode"` 确认导入成功。
- 全仓 grep 确认无 `modules/llm` 残留引用。

## Subtask 拆分

- S1：创建新目录与 `__init__.py`
- S2：迁移 `RoleMode` → `app/models/router.py`
- S3：迁移 `role_router_prompt` → `app/prompts/router.py`
- S4：拆分角色人设 → `app/character/asuna/` 五文件
- S5：删除旧目录与遗留文件
- S6：全仓引用扫描清理

## Acceptance Criteria

- 新目录结构完整存在，旧 `modules/llm/` 与 `__init__ copy.py` 已删除
- `from app.models.router import RoleMode` 导入成功
- `from app.prompts.router import role_router_prompt` 导入成功
- `from app.character.asuna.modes import MODE_INSTRUCTIONS` 导入成功
- grep `modules/llm` 无命中
- `pylint` 通过

## Test Requirements

- 无独立测试；以导入冒烟 + grep 扫描为准。