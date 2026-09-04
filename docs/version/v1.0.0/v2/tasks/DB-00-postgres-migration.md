# DB-00 PostgreSQL 切换与 Alembic 迁移体系

| 字段 | 内容 |
|---|---|
| Task ID | DB-00 |
| Task Name | PostgreSQL 切换与 Alembic 迁移体系 |
| Type | DB |
| Priority | P0 |

## Description

运行时数据库由 SQLite 切换为 PostgreSQL 16+，引入 Alembic 版本化迁移取代 lifespan `create_all`。是 V2 数据层全部任务的前置。repositories 代码零改动（方言差异由 SQLAlchemy 消化），切换成本收敛在 `core/db.py`、settings 与迁移链。

## Scope

- `app/core/db.py`：`create_engine` 方言感知——SQLite 分支保留 `check_same_thread=False`（测试专用）；PostgreSQL 分支去掉该参数、改配连接池
- `app/core/settings.py`：`database_url` 默认 `postgresql+psycopg://asuna:asuna@localhost:5432/asuna`；新增 `db_pool_size=5`、`db_max_overflow=10`、`db_pool_recycle=1800`、`db_pool_pre_ping=True`
- `pyproject.toml`：依赖新增 `alembic`、`psycopg[binary]`
- `migrations/`（`alembic init`）：`env.py` 读 `get_settings().database_url`；**rev1 = baseline V1 四表**（与现存 ORM 结构一致，类型按 PG 方言映射）
- `app/main.py`：lifespan 的 `create_tables()` 退役
- `scripts/migrate_sqlite_to_postgres.py`：存量数据一次性搬运（conversations → messages → conversation_summaries → memories，按外键依赖排序）
- `docker-compose.yml`：本地 PostgreSQL 16 服务（可选）
- tests：HTTP 集成测试基座切 PostgreSQL（测试库 URL 经环境变量注入，`alembic upgrade head` 建表）；单元测试保留内存 SQLite

## Out of Scope

- V2 三张状态表（DB-01 的 rev2）
- asyncpg + AsyncSession 异步化（P2，需重写仓储签名）
- 表结构变更（baseline 保持 V1 现状，只迁移不改动）
- timezone-aware 时间戳（P2）

## Dependencies

- 仅依赖 V1 现状（无 V2 前置，可与 BE-01 并行）

## Input

- `docs/version/v1.0.0/v2/v2-architecture.md` §5.1–5.4
- 现存 `asuna.db`（搬运源，可选执行）

## Output

- `app/core/db.py`、`app/core/settings.py`、`app/main.py`、`pyproject.toml`（修改）
- `migrations/`、`scripts/migrate_sqlite_to_postgres.py`、`docker-compose.yml`（新建）

## Business Rules

1. 生产凭据只从环境变量 / `.env` 注入，源码里的默认连接串仅本地开发缺省（不算密钥泄漏）。
2. 连接池参数进 settings（阈值约定），不硬编码。
3. Alembic 是 schema 唯一真相；`create_all` 退役。唯一豁免：单元测试内存 SQLite 直接 `Base.metadata.create_all`（不走迁移，求快）。
4. rev1 baseline 必须与 V1 ORM 逐一对应（autogenerate 后人工核对字段 / 约束 / 索引）。
5. 搬运脚本幂等：目标表先清后写，可重复执行；执行顺序遵从外键依赖。

## API Dependencies

- 无

## Data Dependencies

- PostgreSQL 16 实例（docker-compose 或本机安装）
- 现存 `asuna.db`（搬运源）

## Permission

- 无

## Error Handling

- engine 按方言分支，未知方言显式抛错（不静默落到错误配置）。
- `alembic upgrade` 失败依赖数据库事务回滚，不留下半套 schema。
- 搬运脚本对缺表 / 空库容错（源表不存在则跳过并输出摘要）。

## Subtask 拆分

- S1：依赖 + 方言感知 engine + settings 连接配置
- S2：`alembic init` + env.py 接 settings + rev1 baseline V1 四表
- S3：lifespan `create_tables()` 退役 + HTTP 集成测试基座切 PG
- S4：docker-compose + 存量数据搬运脚本
- S5：验收（PG 建表核对 + 全量回归）

## Acceptance Criteria

- docker-compose 起本地 PG，`alembic upgrade head` 建出 V1 四表，字段 / 约束 / 索引与 ORM 一致
- V1 全量单元测试在内存 SQLite 下照常通过（零回归）
- HTTP 集成测试连 PostgreSQL 通过（本地无 PG 实例时 skip 并提示）
- V2 全量 pytest 绿
- 搬运脚本对 `asuna.db` 执行后，PG 各表行数与源一致

## Test Requirements

- 单元测试：内存 SQLite（V1 模式不变）
- 集成测试：PostgreSQL（`alembic upgrade head` 建表，无实例时 skip 标记）
- 全程禁止真实 LLM 调用
