# FEISHU-003 — Feishu User / Session 映射

> 上游：[../tasks.md](../tasks.md) FEISHU-003 ｜ 架构：[../architecture.md](../architecture.md) §3（§3.1 映射链 / §3.2 存储设计 / §3.3 隔离保证）｜ 依赖：**FEISHU-001**
> Priority：**P0** ｜ 层级：Identity（本模块唯一涉及 DB schema 的 Task；FEISHU-004 的输入提供方）
> **本 Task 的产出形态**：`open_id` 进入 → 一行 `channel_identities` → 返回 `(internal_user_id, session_id)`。**不含** Webhook、管线调用、消息发送。

---

## 1. Goal

把"外部身份"翻译成"内部身份"（**双向**），并让这个翻译成为**多用户隔离的唯一支点**：

```text
【正向 · 入站】
Feishu open_id
      │
      ▼
ChannelIdentity（通道无关值对象）
      │
      ▼
channel_identity_service.resolve(...)
      │         │
      │         ├─ 查 channel_identities（channel="feishu", external_id=open_id）
      │         └─ 未命中 → 落一行（唯一约束保证并发只有一行）
      ▼
internal_user_id = "feishu:{open_id}"
session_id       = "feishu:{open_id}"
      │
      ▼
（FEISHU-004 原样透传给 agent_service.stream_chat）
```

```text
【反向 · 出站 Proactive（本次修订新增）】
internal_user_id（例："feishu:ou_A"）
      │
      ▼
channel_identity_service.resolve_recipient(internal_user_id, "feishu")
      │         │
      │         ├─ repository.list_by_internal_user(internal_user_id)（走 idx_channel_identities_user）
      │         ├─ 按 channel 精确匹配，取 created_at 最早一行
      │         └─ 未命中 → None（不猜、不兜底、不抛异常）
      ▼
RecipientRef(channel="feishu", external_id="ou_A")
      │
      ▼
（FEISHU-005 的 Proactive 路径：external_id → Feishu Send API）
```

本 Task 交付 6 件事：

1. **一张新表** `channel_identities`（迁移 `0036`）——架构 §3.2 是唯一新增 schema。
2. **一个仓储** `channel_identity_repository`（单表访问 + 并发幂等 upsert + 反查）。
3. **一个服务** `channel_identity_service`（**唯一**读写入口；派生规则在此冻结；**正向 `resolve` + 反向 `resolve_recipient`**）。
4. **一个渠道适配器** `channels/feishu/identity.py`（`InboundMessage → ChannelIdentity`，纯函数、零 IO）。
5. **反向解析**：`internal_user_id → external_id`，供**未来主动消息**定位收件人（architecture §3.4）。这是"飞书能成为主动消息出口"的身份前提。
6. **可验证的隔离保证**：不同 `open_id` → 不同 `user_id` → Conversation / Messages / Memory / World / Inventory / Relationship / Character State **全部天然隔离**。

## 2. Dependencies

| 依赖 | 提供物 | 使用方式 |
|---|---|---|
| **FEISHU-001** | `channels/base.py::ChannelIdentity`（`channel` / `external_user_id` / `tenant` / `display_name`） | 渠道适配器的产出类型 |
| FEISHU-001 | `FeishuError` 家族 | **不使用**（本 Task 不产生飞书 API 错误；DB 错误按既有异常向上抛） |
| **FEISHU-002** | 已通过校验并去重的 `InboundMessage` | 输入的来源（但 003 **只**消费其 `external_user_id` 与 `metadata`，不解析原始事件） |
| 既有 | `app/core/db.py`（`Base` / `SessionLocal` / ORM 行范式） | 新表行必须加入此文件（§6.2 + §15.1） |
| 既有 | `test_db_migration.py::test_alembic_upgrade_matches_orm_metadata` | **约束**：ORM 与 Alembic 列集必须一致（§12.2） |
| 既有 | `tests/conftest.py::_REPO_MODULES` | 新仓储**必须**登记（否则测试连真实 PG 挂起，§15.2） |

> **反向输出（本 Task 必须供给下游）**：`resolve(...)` 返回的 `ResolvedIdentity` 是 FEISHU-004 的**唯一**身份来源。004 不得自行拼 `f"feishu:{open_id}"`，也不得访问 `channel_identities`。

## 3. Scope

**做**：

- 迁移 `0036_channel_identities.py`（`down_revision = "0035"`），含 upgrade/downgrade。
- `app/core/db.py` 新增 `ChannelIdentityRow`（**白名单扩展，见 §15.1**）。
- `app/repositories/channel_identity_repository.py`：`find` / `get_or_create` / `update_identity` / `list_by_internal_user`。
- `app/services/channel_identity_service.py`：`build_internal_user_id` / `build_session_id` / `resolve` / **`resolve_recipient`（反向，本次修订新增）**。
- `app/channels/feishu/identity.py`：`FEISHU_CHANNEL` 常量 + `to_channel_identity(inbound)`。
- 接线：`tests/conftest.py::_REPO_MODULES` 追加新仓储模块（**必须**）。

**不做**（见 §14）：Webhook、管线调用、回复发送、**主动消息触发方（Autonomy / Scheduler / Policy）**、账号绑定流程、用户表、会话表、`conversations` 等既有表结构变更、跨进程一致性。

## 4. Files

### New Files

```text
migrations/versions/0036_channel_identities.py
app/repositories/channel_identity_repository.py
app/services/channel_identity_service.py
app/channels/feishu/identity.py
tests/unit/test_feishu_identity.py            # 派生规则纯函数
tests/integration/test_channel_identity.py    # 仓储幂等/并发 + 隔离矩阵
```

### Modified Files（共 2 个，其中 1 个不在设计文档原白名单内）

```text
app/core/db.py             # 新增 ChannelIdentityRow 一个类（★ 白名单扩展，理由见 §15.1）
tests/conftest.py          # _REPO_MODULES 追加 channel_identity_repository（★ 强制，见 §15.2）
```

### Forbidden Files

```text
api/**                          # 本 Task 不动路由（002 已建）
application/chat_pipeline.py    # 管线零修改
services/**（既有域服务）        # 只新增 channel_identity_service.py
repositories/**（既有仓储）      # 只新增 channel_identity_repository.py
character/**  chains/**  prompts/**  models/**
api/v1/chat.py  api/v1/schemas.py
migrations/versions/0001~0035   # 既有迁移一律不得修改（只新增 0036）
alembic.ini
```

## 5. Architecture / Data Flow

### 5.1 正常路径

```text
FEISHU-002 → adapter.handle_inbound_message(inbound)
                        │
                        ▼
        channels/feishu/identity.py
        ├─ FEISHU_CHANNEL = "feishu"
        ├─ to_channel_identity(inbound) → ChannelIdentity(
        │       channel           = "feishu",
        │       external_user_id  = inbound.external_user_id,     # ← open_id
        │       tenant            = inbound.metadata["tenant_key"],
        │       display_name      = None)
        │   （不查库、不计算 user_id、不 import repositories）
                        │
                        ▼
        services/channel_identity_service.py
        ├─ build_internal_user_id(channel, external_id) → f"{channel}:{external_id}"
        ├─ build_session_id(channel, external_id)       → f"{channel}:{external_id}"
        └─ resolve(channel, external_id, union_id=…, tenant_key=…, display_name=…)
                        │
                        ▼
        repositories/channel_identity_repository.py
        ├─ find(channel, external_id) → row | None
        └─ get_or_create(...) → row      # 唯一约束 + IntegrityError 回查（幂等）
                        │
                        ▼
        ResolvedIdentity(channel, external_id, internal_user_id, session_id, created)
                        │
                        ▼
        （FEISHU-004）agent_service.stream_chat(session_id, internal_user_id, text, llm, trace)
```

### 5.2 关键不变式

| 不变式 | 含义 |
|---|---|
| **确定性派生** | `internal_user_id` / `session_id` 只由 `(channel, external_id)` 决定 → 同一 `open_id` **在任何情况下都不可能拿到两个不同 user_id** |
| **表是权威** | 派生是**默认值**；`channel_identities` 是权威记录（未来账号绑定只改表内一行，映射规则与管线都不动） |
| **唯一入口** | 读写只经 `channel_identity_service`；`channels/**` **不得**直连 `repositories`（tasks.md AC-6） |
| **服务不依赖 channels** | `channel_identity_service` **不得** import `app.channels.*`（含 `base.py`）——架构 §2.2 反向引用禁令（§15.3） |
| **不建第二套用户/会话** | 不新增 users / sessions 表；身份仍以既有 `conversations.user_id` 等承载 |
| **零既有表变更** | `conversations` / `messages` / `memories` / `worlds` 等**列集不变** |

## 6. Detailed Implementation

### 6.1 迁移 `0036_channel_identities.py`

```text
revision      = "0036"
down_revision = "0035"
```

`upgrade()`：`op.create_table("channel_identities", ...)` + `op.create_index(...)`
`downgrade()`：`op.drop_index(...)` 后 `op.drop_table("channel_identities")`（严格逆序，对齐 0017 的写法）

- **新表无需 `batch_alter_table`**（0035 的 SQLite 注意事项只作用于 ALTER CONSTRAINT；`create_table` 在两方言通用）。
- 迁移文件风格对齐既有：`"""<中文标题>"""` + revision 注释块 + `from typing import Sequence, Union` + 模块级 `revision` / `down_revision`。
- **D9**（列集与 ORM 一致性）：`0036` 建立的列集必须与 §6.2 的 ORM 行**逐列相等**，由 `test_alembic_upgrade_matches_orm_metadata` 守门。

### 6.2 ORM 行（`app/core/db.py`）

```text
class ChannelIdentityRow(Base):
    __tablename__ = "channel_identities"

    channel             : str            PK₁, nullable=False
    external_id         : str            PK₂, nullable=False
    internal_user_id    : str            nullable=False
    session_id          : str            nullable=False
    external_union_id   : str | None     nullable=True
    external_tenant_key : str | None     nullable=True
    display_name        : str | None     nullable=True
    status              : str            nullable=False, default="active", server_default="active"
    created_at          : datetime       nullable=False
    updated_at          : datetime       nullable=False

    __table_args__ = (
        PrimaryKeyConstraint("channel", "external_id"),      # 见 §8 说明
        CheckConstraint("status IN ('active', 'inactive')", name="ck_channel_identities_status"),
        Index("idx_channel_identities_user", "internal_user_id"),
    )
```

- 使用与既有 40+ 行完全相同的 `Mapped[...] = mapped_column(...)` 写法。
- **必须放在 `app/core/db.py`**：见 §15.1（`Base.metadata` 一致性 + 内存 SQLite 建表 + `test_db_migration` 的列集校验）。
- `CharacterStateRow` / `RelationshipStateRow` 等既有行**不动**。

### 6.3 仓储（`channel_identity_repository.py`）

模块级函数 + `from app.core.db import ChannelIdentityRow, SessionLocal`（既有仓储惯例）：

| 函数 | 输入 | 输出 | 语义 |
|---|---|---|---|
| `find(channel, external_id)` | 复合键 | `ChannelIdentityRow \| None`（`expunge` 后返回） | 只读 |
| `get_or_create(channel, external_id, internal_user_id, session_id, *, union_id=None, tenant_key=None, display_name=None)` | 复合键 + 派生值 + 可选元数据 | `(row, created: bool)` | **幂等**：先查 → 无则插 → `IntegrityError` → `rollback` → 回查 |
| `update_identity(channel, external_id, *, internal_user_id=None, session_id=None, display_name=None)` | 复合键 + 待改字段 | `row \| None` | 账号绑定的预留入口（**本阶段不调用**） |
| `list_by_internal_user(internal_user_id)` | 内部用户 ID | `list[row]` | 反查（**`resolve_recipient` 的数据源** + 隔离测试 + 未来多通道） |

**`get_or_create` 的并发正确性**（照搬 `background_job_repository.enqueue_job` 的既有范式）：

```text
1. 查：命中 → 直接返回 (row, created=False)          ← 稳态零写
2. 未命中 → add(row) + commit
3. except IntegrityError:
       rollback()
       row = 再查一次（此时必然存在，因为唯一约束保证另一个并发者已提交）
       return (row, created=False)                   ← 不报错、不重复插
```

**查询不按 `status` 过滤**：第一阶段没有停用路径，`status` 为**预留字段**（账号解绑/停用属未来账号绑定 Task）。若有过滤需求，在 service 层表达，不在仓储层隐式过滤——否则"查不到"与"被停用"无法区分。

**返回脱离 ORM 的实例**：`session.expunge(row)`（对齐 `list_jobs`），避免调用方持有已关闭 session 的实体（懒加载会抛错）。

### 6.4 服务（`channel_identity_service.py`）

```text
build_internal_user_id(channel: str, external_id: str) -> str    # f"{channel}:{external_id}"
build_session_id(channel: str, external_id: str) -> str          # f"{channel}:{external_id}"
resolve(channel: str, external_id: str, *, union_id=None, tenant_key=None, display_name=None)
        -> ResolvedIdentity
resolve_recipient(internal_user_id: str, channel: str)
        -> RecipientRef | None                                   # ★ 本次修订新增（反向）
```

```text
ResolvedIdentity(frozen dataclass)
  channel: str
  external_id: str
  internal_user_id: str
  session_id: str
  created: bool          # 是否本次新建（观测/测试用）
```

- **`resolve`（正向）**：所有入站调用方（含 FEISHU-004）的唯一入口。内部先算派生值 → `get_or_create` → 返回 `ResolvedIdentity`。用于 `open_id → internal_user_id / session_id`。
- **`resolve_recipient`（反向，本次修订新增）**：所有**主动消息**调用方的唯一入口，用于 `internal_user_id → external_id`。实现为 `repository.list_by_internal_user(internal_user_id)` 后按 `channel` 精确匹配、取 `created_at` 最早一行，构造 `RecipientRef(channel=..., external_id=...)`；未命中返回 `None`。
  - **为什么不能用 `session_id` 反推**：`feishu:{open_id}` 只是**默认派生值**，表才是权威记录（architecture §3.1 / §3.4）。未来任何一次账号绑定都会让"拆前缀"送错人。
  - **返回 `RecipientRef`（来自 `channels/base.py` 契约）**：这里是**唯一**允许 `services` 触碰 `app.channels.base` 的场景（架构 §2.2 R2：契约可被核心层 import，实现不可）。**仍不得** import `app.channels.feishu`。
  - **未命中必须返回 `None`**，不得抛异常、不得兜底到"别的收件人"、不得猜测。
- **幂等语义**：`resolve` 重复调用返回**完全相同**的 `internal_user_id` / `session_id`，仅 `created` 变化。
- **入参用标量而非 `ChannelIdentity`**：因为服务**不得** import `app.channels.<impl>`，且入站方向连 `ChannelsIdentity` 这类契约对象也无必要（标量更直接）。渠道侧对象在 `channels/feishu/identity.py` 拆成标量后传入。
- **根因B 规避**：服务**不** `from app.core.db import SessionLocal`（DB 访问在仓储层），因此**无需**加入 `conftest._SERVICE_DB_MODULES`（该清单只针对 service/application 层自持 SessionLocal 的模块）。
- **派生规则为何放服务而不是渠道**：`f"{channel}:{external_id}"` 是**通道无关**的通用规则（不是 Feishu 特有），放服务层既能被任意渠道复用，又避免 `services → channels` 的违规反向依赖。这是本 Task 的一个关键取舍（§15.3）。

### 6.5 渠道适配器（`channels/feishu/identity.py`）

```text
FEISHU_CHANNEL = "feishu"

to_channel_identity(inbound: InboundMessage) -> ChannelIdentity
    channel          = FEISHU_CHANNEL
    external_user_id = inbound.external_user_id        # ← 已是 open_id（002 保证）
    tenant           = inbound.metadata.get("tenant_key")
    display_name     = None                            # 飞书显示名需额外接口，第一阶段不取
```

- **纯函数、零 IO**：不查库、不算 user_id、不 import repositories → 满足 tasks.md AC-6。
- `display_name` 留空是**有意的**：取飞书昵称需要额外 API 调用与 `contact` 权限，与"文本最小闭环"无关；表里保留该列，未来补。

### 6.6 隔离保证的实现方式

隔离**不需要任何新代码**——它由既有代码的 `user_id` 索引自动生效。本 Task 的职责是**证明**它：

| 资源 | 隔离键（既有） | 隔离如何发生 |
|---|---|---|
| Conversation | `conversations.id = session_id` + `conversations.user_id` | 不同 open_id → 不同 session_id |
| Messages | `messages.conversation_id` | 随会话隔离 |
| Memory | `memories.user_id` | 不同 internal_user_id |
| World / Inventory | `worlds.world_id = world_repository.world_id_for(user_id)` = `f"home:{user_id}"` | → `home:feishu:A` / `home:feishu:B` |
| Relationship / Character State | `relationship_state.user_id` / `character_state.user_id`（均为主键） | 不同 internal_user_id |

**验证方式**（§12.2 落地为测试）：对 `open_id=A` 与 `open_id=B` 各跑一次最小写入链，然后交叉读取断言为空。**这是"多用户隔离"从设计假设变成运行事实的唯一证据。**

**额外隔离决策（与架构 §3.3 一致）**：身份键只用 `open_id`；`chat_id` 不参与映射（否则群聊会污染）。群聊在 FEISHU-002 已被拒，本 Task 无需再判。

## 7. Interfaces

| 能力 | 输入 | 输出 | 语义 |
|---|---|---|---|
| 派生内部用户 ID | `channel`, `external_id` | `str` | 纯函数；确定性 |
| 派生会话 ID | `channel`, `external_id` | `str` | 纯函数；当前与 user_id 同值（**分开成两个函数**，为未来"一用户多会话"留出口） |
| 解析身份 | 标量 + 可选元数据 | `ResolvedIdentity` | 幂等；入站方向的唯一入口 |
| **解析收件人（反向）** | `internal_user_id`, `channel` | `RecipientRef \| None` | **本次修订新增**；仅出站 Proactive 使用；未命中返回 `None`（不猜） |
| 组装通道身份 | `InboundMessage` | `ChannelIdentity` | 纯函数；零 IO |
| 单表读写 | 见 §6.3 | 行 / 列表 | 只做数据访问，无业务判断 |

**命名与语义冻结**：`FEISHU_CHANNEL = "feishu"` 是 `external_id` 命名空间的一部分，一旦上线**不可更改**（改了等于换身份，会让所有老用户"失忆"）。

## 8. Data Model

### 8.1 `channel_identities`

| 列 | 类型 | NULL | 默认 | 说明 |
|---|---|---|---|---|
| `channel` | String | ❌ | — | 通道标识，第一阶段恒 `"feishu"` |
| `external_id` | String | ❌ | — | 飞书 `open_id` |
| `internal_user_id` | String | ❌ | — | `f"{channel}:{external_id}"` |
| `session_id` | String | ❌ | — | 当前同 `internal_user_id` |
| `external_union_id` | String | ✅ | NULL | 预留：跨应用身份合并 |
| `external_tenant_key` | String | ✅ | NULL | 预留：多租户 |
| `display_name` | String | ✅ | NULL | 可读名（日志可读性；当前不取） |
| `status` | String | ❌ | `'active'` | 预留：`active` / `inactive` |
| `created_at` | DateTime | ❌ | — | 写入时刻（`datetime.now()`，对齐既有表：非时区感知） |
| `updated_at` | DateTime | ❌ | — | 最后更新 |

**约束与索引**

| 名称 | 类型 | 列 | 理由 |
|---|---|---|---|
| （复合主键） | PRIMARY KEY | `channel`, `external_id` | **即唯一约束**——架构 §3.2 要求的 `UNIQUE(channel, external_id)` 由此满足，**不再额外建冗余 unique index** |
| `ck_channel_identities_status` | CHECK | `status IN ('active','inactive')` | 值域文档化（对齐既有表惯例）。**注意**：日后拓宽取值需用 0035 的 `batch_alter_table` 模式（SQLite 不支持 ALTER CONSTRAINT） |
| `idx_channel_identities_user` | INDEX | `internal_user_id` | 反查（隔离测试 + 未来多通道/账号绑定） |

**downgrade**：`drop_index` → `drop_table`，无数据迁移（新表，回滚即消失）。

### 8.2 为什么 `session_id` 与 `internal_user_id` 分开存

值相同，但**语义不同**：`internal_user_id` 是"人"，`session_id` 是"对话"。本阶段一人一对话，未来若要"新建对话"（清空上下文但保留记忆），只需改 `session_id` 而不动 `internal_user_id`。**现在分开，未来不必改表。**

## 9. Error Handling

| 情形 | 处理 | 说明 |
|---|---|---|
| `open_id` 为空/空白 | `ValueError`（fail-fast） | 由 `base.py` 守卫或服务入口校验；FEISHU-002 已在解析期丢弃无 open_id 的事件，此处是第二道 |
| `channel` 为空 | `ValueError` | 同上 |
| 唯一冲突（并发首建） | **不算错误**：`rollback` + 回查 → 返回既有行 | §6.3 |
| DB 不可用 / 连接失败 | 异常**向上抛**到 FEISHU-002 的 `handle_inbound_message` 兜底 | 归属架构 §6.2 #6：**不调管线**，尝试发兜底文案；发不出则静默 |
| 行存在但 `status='inactive'` | 本阶段照常返回（不过滤） | 无停用路径；未来账号绑定 Task 再定义语义 |
| `display_name` 缺失 | 正常（列可空） | 不阻塞映射 |

**不新增错误类型**：身份映射失败就是 DB 失败或参数非法，前者用既有 SQLAlchemy 异常、后者用 `ValueError`。**不引入 `IdentityError` 之类的空壳异常**——FEISHU-002/004 的兜底只区分"抛了/没抛"。

## 10. Concurrency / Idempotency

### 10.1 并发首建（本 Task 的核心验收点）

```text
Request A ─┐
Request B ─┼─ 同时 resolve("feishu", "ou_xxx")
Request C ─┘
                ▼
        唯一约束 (channel, external_id)
                ▼
        最终恰好 1 行
        且 A/B/C 得到的 internal_user_id 完全一致
```

**双重保证**（这是"不可能出现 duplicate identity / 不可能出现 different internal_user_id"的理由）：

1. **确定性派生**：三个请求算出的 `internal_user_id` **在数学上相同**（同一个 `(channel, external_id)`）→ "不同 user_id" 在结构上不可能发生。
2. **复合主键**：数据库拒绝第二行 → "重复行" 在结构上不可能发生。

因此并发处理**只需**处理 `IntegrityError`，不需要分布式锁、不需要 `SELECT FOR UPDATE`、不需要重试退避。

### 10.2 事务边界

| 写操作 | 事务 | 说明 |
|---|---|---|
| 首建 | **单行单提交**（`with SessionLocal() as session` + `commit`） | 无跨表、无跨行事务需求 |
| 稳态读 | 无写（`find` 短路） | 每轮对话只在**首次**产生一次插入 |
| 账号绑定（未来） | 单行 UPDATE | 本 Task 只提供入口，不调用 |

**无跨模块事务**：本 Task **不**与 `conversations` / `worlds` 同事务。原因：`conversations` 由管线的 `save_turn` 在后续步骤建立，且**即使身份行存在而会话行尚未建立也是合法的中间态**（下一轮自动补建）。强行跨表事务会把入站路径变成多表写，得不偿失。

### 10.3 幂等总结

| 操作 | 幂等键 | 重复调用的结果 |
|---|---|---|
| `resolve` | `(channel, external_id)` | 返回同一身份；仅 `created` 从 `True` 变 `False` |

## 11. Security

| 项 | 要求 |
|---|---|
| **表内无凭据** | `channel_identities` **不存**任何密钥/token；只存标识与派生 ID |
| **`open_id` 非凭据** | 允许入日志与库（排障必需）；`union_id` / `tenant_key` 同性质 |
| **派生 ID 不可猜** | `feishu:{open_id}` 含外部 ID，**不构成访问控制**——真正的授权仍是"飞书事件签名"（FEISHU-002）。本表**不是**鉴权表 |
| **日志脱敏** | 复用 001 的 `secret_values()` / `_scrub`；本 Task 产出的日志不含密文与 token |
| **不记录消息正文** | 本表与仓储**不**落任何对话内容（`memories` / `messages` 才有，且属管线） |

## 12. Testing

### 12.1 `tests/unit/test_feishu_identity.py`（纯函数，零 DB）

```text
[ ] build_internal_user_id("feishu","ou_x") == "feishu:ou_x"
[ ] build_session_id("feishu","ou_x")       == "feishu:ou_x"
[ ] 确定性：同输入重复调用结果全等
[ ] 注入性（不同 A/B 不冲突）：A≠B → 派生值不同
[ ] 前缀隔离：feishu 派生值 ≠ web 的 uuid4 形态（含 ":" 前缀）
[ ] 非法输入：空 channel / 空 external_id / 纯空白 → ValueError
[ ] FEISHU_CHANNEL 常量 == "feishu"
[ ] to_channel_identity(inbound)：channel/external_user_id/tenant 映射正确；零 IO（无 repository import，
    用 sys.modules 或静态断言证明 —— 见 FEISHU-006 的边界断言）
[ ] metadata 缺 tenant_key 时 tenant is None（不抛错）
```

### 12.2 `tests/integration/test_channel_identity.py`（内存 SQLite，`db_session_factory`）

```text
迁移与 ORM 一致性
[ ] alembic upgrade head → downgrade → upgrade 往返成功（PG 可用时）
[ ] 列集：channel_identities 的 inspector 列名集合 == ORM 列名集合（D9 口径）
[ ] 复合主键存在；idx_channel_identities_user 存在

幂等
[ ] 首次 resolve → created=True；第二次 → created=False；两者 internal_user_id / session_id 全等
[ ] 库中行数恒为 1

并发首建（核心）
[ ] N 个并发 resolve("feishu", "ou_A")（线程或 asyncio.gather）→ 无异常、行数 == 1、
    返回值全等（断言"不同 internal_user_id 不可能发生"）
[ ] 人为制造 IntegrityError 路径（先插后让另一路径走 add/commit）→ 回查成功、不抛错

多用户隔离矩阵（核心）
[ ] open_id=A → conversation/messages 写入后，以 B 的身份读取为空
[ ] memories：A 写入 → list_by_user(B) 为空
[ ] worlds：world_repository.world_id_for("feishu:A") == "home:feishu:A"，
    且 A 的 world 与 B 的 world 是不同行（含 list_objects 交叉为空）
[ ] relationship_state / character_state：A 写 → B 读为默认/空
[ ] 交叉断言：A≠B 的 internal_user_id、session_id、world_id 三者同时成立

仓储细节
[ ] find 未命中返回 None；find 命中返回脱离 session 的实例（可安全读取字段）
[ ] update_identity 能改 internal_user_id / session_id / display_name；未命中返回 None
[ ] list_by_internal_user 只返回该内部用户的行

反向解析（本次修订新增）
[ ] resolve_recipient("feishu:ou_A", "feishu") → RecipientRef(channel="feishu", external_id="ou_A")
[ ] RecipientRef 的字段名不含飞书特有名词（open_id 等）—— 与 001 的基元白名单一致
[ ] 未知 internal_user_id → None（不抛异常、不返回空字符串、不兜底）
[ ] channel 不匹配（如查 "feishu:ou_A" 但 channel="web"）→ None
[ ] 同 internal_user_id 多行（人为造两行不同 channel）→ 按 channel 精确命中对应行
[ ] 确定性：重复调用返回同一 external_id（多行时取 created_at 最早，不随查询顺序漂移）
[ ] 不以 session_id 反推：构造"session_id 与 external_id 不一致"的行（模拟账号绑定后状态），
    resolve_recipient 仍以表内 external_id 为准（断言返回表内值，而非 session_id 前缀）
[ ] 只读：resolve_recipient 不产生任何写入（行数不变）
```

### 12.3 测试基建

| 需要 | 做法 |
|---|---|
| 内存 SQLite 建表 | conftest autouse `_offline_repos` 的 `Base.metadata.create_all` 会自动建 `channel_identities`（**前提**：行已加入 `core/db.py`，§15.1） |
| 仓储 SessionLocal 替换 | **必须**把 `channel_identity_repository` 加入 `_REPO_MODULES`（§15.2） |
| 隔离矩阵 | 复用既有 `conversation_repository` / `memory_repository` / `world_repository` / `relationship_repository` 的写读 API（测试里直接调用，**证明不需要为飞书写任何隔离代码**） |
| PG 迁移往返 | 归入 `xdist_group("migration")`，无 PG 时自动 skip（既有行为） |

**执行级别**：Focused（2 个新文件）→ Module → **Integration**（`pytest -m integration`，改 DB/迁移/仓储时门槛要求）→ Fast。

## 13. Acceptance Mapping

> 对齐 [../tasks.md](../tasks.md) FEISHU-003 的 6 条 AC。

```text
[ ] 首次接触生成 internal_user_id = "feishu:{open_id}" 与 session_id = "feishu:{open_id}"，
    并落一行 channel_identities                                                       (AC-1)
[ ] 重复接触幂等：多次调用返回同一 user_id / session_id，表中仍只有一行；
    并发同一 external_id 也只落一行                                                    (AC-2)
[ ] session_id 前缀 feishu:，与 Web uuid4 会话不冲突，且不进 default_user              (AC-3)
[ ] 隔离断言：A/B 各自 conversation / messages / memories / worlds(home:{user_id}) /
    relationship 互不可见（A 写入后以 B 读取为空）                                      (AC-4)
[ ] alembic upgrade → downgrade 往返成功；ORM 与迁移列集一致                           (AC-5)
[ ] channel_identity_service 是唯一读写入口；channels/feishu/identity.py 不直连 repositories (AC-6)
[ ] **反向解析（本次修订新增）**：resolve_recipient("feishu:ou_A","feishu") 返回
    RecipientRef(channel="feishu", external_id="ou_A")；未知 internal_user_id → None；
    不抛异常、不兜底、不以 session_id 前缀反推
[ ] services 只 import app.channels.base（契约），不 import app.channels.feishu（R1/R2 断言）
[ ] 既有表零变更：conversations / messages / memories / worlds 列集不变（git diff 不含这些表的类）
[ ] 既有迁移零修改：migrations/versions/0001~0035 未被 touch
[ ] 既有文件改动仅 app/core/db.py（+1 行类、白名单扩展）与 tests/conftest.py（+1 元组项）
```

## 14. Out of Scope

| 不做 | 归属 / 理由 |
|---|---|
| Webhook 路由、验签、解密、去重 | FEISHU-002 |
| 调管线 / LLM / 回复累积 | FEISHU-004 |
| 出站发送 | FEISHU-005 |
| 错误矩阵收口、静态断言、冒烟清单 | FEISHU-006 |
| **Web ↔ 飞书账号绑定**（把 `internal_user_id` 改成既有 Web 用户） | 明确不做（架构 §7.2）；本 Task 只**预留** `update_identity` 入口 |
| 用户表 / 会话表 / 第二套 Memory | 明确不做（架构 §3.2） |
| 一用户多会话 | 明确不做（`session_id` 已分开成函数，留出口） |
| `display_name` 取飞书昵称 | 不做（需 `contact` 权限与额外 API 调用） |
| 停用 / 解绑流程（`status='inactive'` 的语义） | 不做（字段预留） |
| 跨进程一致性 / 分布式锁 | 不做（§10.1 已论证不需要） |

## 15. Implementation Notes

### 15.1 `app/core/db.py` 为何必须扩白名单（**已确认并回填**）

设计文档（tasks.md 头部）的既有文件白名单**已包含** `app/core/db.py`（本条理由即回填依据）。本 Task **必须**修改 `app/core/db.py`，理由有 3 条且无法规避：

1. **既有惯例**：全仓库 40+ 个 ORM 行**全部**集中在此单文件（`Conversation`、`WorldRow`、`OutboxEventRow`…）。把新行放别处会打破唯一惯例。
2. **`Base.metadata` 必须包含新表**：`tests/conftest.py::_offline_repos` 用 `Base.metadata.create_all(engine)` 建内存表。若行不在（或模块未被导入），测试将**看不到该表**，所有集成测试直接失败。
3. **`test_db_migration.py::test_alembic_upgrade_matches_orm_metadata`** 遍历 `Base.metadata.sorted_tables` 校验列集与 PG 一致——行不在 metadata 中，该守门就失去意义。

改动极小：**只新增 1 个类**，不改任何既有行。

### 15.2 `tests/conftest.py::_REPO_MODULES` 是**强制**修改

`_offline_repos` 通过遍历硬编码元组 `_REPO_MODULES` 来替换各仓储模块的 `SessionLocal`。**新仓储未登记 → autouse fixture 不替换它 → 测试会连真实 PostgreSQL（`.env`）并挂起**（TESTING.md §6「根因B」的模式，`services` 层对应 `_SERVICE_DB_MODULES`）。

```text
必做：_REPO_MODULES 追加 channel_identity_repository
非必做：_SERVICE_DB_MODULES —— channel_identity_service 不持有 SessionLocal（DB 访问在仓储），故无需登记
```

**验证方式**：新增集成测试若能在**不设** `TEST_USE_POSTGRES` 的情况下通过，即证明登记生效。

### 15.3 反向依赖禁令带来的关键取舍（**易错点**）

架构 §2.2 规定：`application` / `services` / `repositories` **不得** import `app.channels.*`。这直接约束了本 Task 的两个设计点：

| 问题 | 若违规的写法 | 本 Task 的写法 |
|---|---|---|
| 派生规则放哪 | `channel_identity_service` import `channels/feishu/identity.py` ❌ | 规则放**服务**（`f"{channel}:{external_id}"`，通道无关）；`channels/feishu/identity.py` 只组装 `ChannelIdentity`，不做派生 ✅ |
| 服务入参类型 | `resolve(identity: ChannelIdentity)` ❌（需 import `app.channels.base`） | `resolve(channel: str, external_id: str, ...)` 标量入参 ✅ |

> **备选方案（未采用）**：允许 `services → app.channels.base` 单一例外（`base.py` 只含通道无关 DTO，导入无实害）并把该例外写进 FEISHU-006 的断言白名单。未采用原因：架构把禁令写成绝对条款，且标量入参只需 4 个参数，收益不足以换取规则的口子。**若团队倾向备选，需同步修改 architecture.md §2.2 与 FEISHU-006 的断言白名单。**

### 15.4 与 tasks.md 的偏差记录

| tasks.md 原文 | 本 Detail | 原因 |
|---|---|---|
| 新增 `channels/feishu/identity.py`（open_id → user_id/session_id 派生规则） | identity.py **只做适配组装**，派生规则移到 service | §15.3 的反向依赖禁令 |
| 未列 `app/core/db.py` | 必须修改 | §15.1 |
| `get_or_create` 在 repository 与 service 都提到 | 冻结为：**repository 提供 `get_or_create`（数据层幂等）；service 提供 `resolve`（业务入口）** | 避免"两个同名入口"的职责歧义 |

### 15.5 命名冻结

```text
FEISHU_CHANNEL = "feishu"        # 上线后不可改（改了 = 换身份 = 全员失忆）
internal_user_id 格式 = f"{channel}:{external_id}"
```

**迁移提示**：若未来需要把 `feishu:{open_id}` 与既有 Web 用户合并，**不要**改派生规则，而是用 `update_identity` 改表内 `internal_user_id`（表是权威——这正是架构 §3.1 把表定义为权威记录的原因）。

### 15.6 Implementation Order

```text
1. 迁移 0036（create_table + index）+ core/db.py 的 ChannelIdentityRow（先跑 PG 往返 + 列集一致性）
2. repository（find / get_or_create / update_identity / list_by_internal_user）+ conftest 登记
3. service（派生函数 + resolve + ResolvedIdentity）
4. channels/feishu/identity.py（常量 + to_channel_identity）
5. tests/unit（派生规则）→ tests/integration（幂等 / 并发 / 隔离矩阵）
6. Focused → Module → Integration（改 DB 的门槛要求）
7. 收口：git status 无临时产物；确认 0001~0035 零改动
```
