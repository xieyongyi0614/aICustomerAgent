# V8 Persistence 设计

> 四张新表（迁移 0017 一次建齐）+ 保留策略。既有 16 张表零改动。

## 1. 数据分类与寿命

| 类别 | 内容 | 寿命 | 说明 |
|---|---|---|---|
| World 状态 | worlds / world_entities / world_environment(列) / world_events(active) | 随用户存在，不 TTL | 世界是长期状态 |
| World 历史 | world_events(completed/cancelled/expired) | 90 天 | 完结事件是记忆素材 + 叙事连续性 |
| 快照 | world_snapshots | 30 天 / 每世界保留 ≤20 份 | 恢复"昨天晚上" |
| notes | world 行内短期备注 | 一轮语义，装配后清除 | 解释器 → 下轮上下文 |

## 2. 表结构（迁移 0017，风格对齐 0016；JSON 承载复合结构）

### worlds

```sql
CREATE TABLE worlds (
    id              VARCHAR PRIMARY KEY,          -- world_id（"home"）
    user_id         VARCHAR NOT NULL,
    name            VARCHAR NOT NULL,
    time_mode       VARCHAR NOT NULL,             -- real_sync/simulated/story（ck）
    sim_time        TIMESTAMP NULL,
    sim_rate        DOUBLE PRECISION NULL,        -- simulated 模式速率
    current_location VARCHAR NOT NULL,            -- "home.living_room"
    environment     JSON NOT NULL,                -- 天气/温度/光照/噪声/氛围 + updated_by
    notes           JSON NOT NULL DEFAULT '[]',   -- 短期备注
    created_at      TIMESTAMP NOT NULL,
    updated_at      TIMESTAMP NOT NULL,
    CONSTRAINT ck_worlds_time_mode CHECK (time_mode IN ('real_sync','simulated','story')),
    CONSTRAINT uq_worlds_user UNIQUE (user_id)    -- 每用户一个默认世界
);
```

### world_entities

```sql
CREATE TABLE world_entities (
    id            VARCHAR PRIMARY KEY,            -- "watermelon_001"
    world_id      VARCHAR NOT NULL REFERENCES worlds(id),
    name          VARCHAR NOT NULL,
    aliases       JSON NOT NULL DEFAULT '[]',
    category      VARCHAR NOT NULL,               -- food/tool/furniture/…（ck 词表）
    location_id   VARCHAR NOT NULL,
    state         VARCHAR NOT NULL,
    quantity      DOUBLE PRECISION NOT NULL DEFAULT 1,
    properties    JSON NOT NULL DEFAULT '{}',     -- expiry_at 等（有界）
    status        VARCHAR NOT NULL,               -- active/destroyed（ck）
    last_action_at TIMESTAMP NULL,
    created_at    TIMESTAMP NOT NULL,
    updated_at    TIMESTAMP NOT NULL,
    -- idx: (world_id, location_id) (world_id, status) (world_id, last_action_at)
    -- ck: category IN (...)、status IN ('active','destroyed')
);
```

### world_events

```sql
CREATE TABLE world_events (
    id            VARCHAR PRIMARY KEY,            -- "evt_xxx"
    world_id      VARCHAR NOT NULL REFERENCES worlds(id),
    type          VARCHAR NOT NULL,
    title         VARCHAR NOT NULL,
    importance    VARCHAR NOT NULL,               -- low/normal/high（ck）
    status        VARCHAR NOT NULL,               -- scheduled/active/completed/cancelled/expired（ck）
    started_at    TIMESTAMP NULL,
    due_at        TIMESTAMP NULL,
    completed_at  TIMESTAMP NULL,
    payload       JSON NOT NULL DEFAULT '{}',     -- memory_materialized 标志在此
    source        VARCHAR NOT NULL,               -- user_mention/manual/autonomy（ck）
    created_at    TIMESTAMP NOT NULL,
    updated_at    TIMESTAMP NOT NULL
    -- idx: (world_id, status, due_at) (world_id, status, importance)
);
```

### world_snapshots

```sql
CREATE TABLE world_snapshots (
    id          VARCHAR PRIMARY KEY,
    world_id    VARCHAR NOT NULL REFERENCES worlds(id),
    label       VARCHAR,
    state       JSON NOT NULL,                    -- 整包：sim_time/location/environment/entities/events
    created_at  TIMESTAMP NOT NULL
    -- idx: (world_id, created_at)
);
```

- 世界行 `environment` 直接用 JSON 列（单行单世界，独立表无收益）。
- ORM 集中 `app/core/db.py`，仓储 `app/repositories/world_repository.py`（模块级函数：ensure_world / save_entities / list_by_location / list_due_events / save_snapshot / load_snapshot / …）。

## 3. 快照与恢复

- 快照触发：手动端点（P0）+ 显著迁移自动采样（P2：每次 Destroyed/Expired 类迁移后，按 world 每小时 ≤1 份限频）。
- 恢复语义（P2）：整包覆盖 entities/environment/events 当前态 + world 行 location/sim_time；**Character 状态不回滚**（时间不可倒流，叙事约束）；恢复动作本身先打一份"恢复前"快照。
- "恢复昨天晚上状态" = `load_snapshot(时间邻域最新)` → restore，全程 debug API。

## 4. 容量与体积估算

- 每 turn 世界读：worlds 1 行 + entities 按位置索引（≤10 行）+ events 索引查询（≤10 行）——毫秒级。
- 实体增长：由用户消息驱动，单机调试台月增量 < 1e3 行；active 实体上限（配置默认 200，超出拒新建 + note）。
- 快照整包 ~ 数 KB；20 份/世界 ≤ 100KB。
- 事件上限：活跃 ≤20（配置）；完结事件 90 天 TTL。

## 5. 保留策略实现

- 复用 V7.8 清理循环形态：observability 循环之外**不新增循环**——world 的 TTL 清理（完结事件 90d / 快照 30d/20 份）挂进同一 lifespan 低频循环（清理循环改为串联 observability + world 两段，各自容错），或 world_repository.save 路径惰性 prune（事件完结时顺带）——实现取"惰性为主 + 循环兜底"，两处都幂等。

## 6. 配置组（`app/core/settings.py` world_* 组）

```text
world_enabled                      true    总开关（false = 回到 V7.8 行为）
world_time_mode                    real_sync  real_sync/simulated/story
world_sim_rate                     1.0     simulated 模式时间流速
world_context_char_budget          600     世界段 prompt 预算
world_nearby_objects_limit         3
world_salient_events_limit         3
world_interpreter_enabled          true    确定性解释器
world_llm_assist_enabled           false   LLM 辅助解释（采样）
world_llm_assist_sample_rate       0.2
world_active_entities_limit        200
world_active_events_limit          20
world_event_grace_hours            6       active 超宽限 → expired
world_memory_bridge_enabled        true    事件完结 → 记忆候选
world_memory_importance_json       {"normal":0.6,"high":0.8}
world_event_retention_days         90
world_snapshot_retention_days      30
world_snapshot_max_per_world       20
```

## 7. 迁移与测试纪律

- 迁移 0017 一次建齐四表；`alembic upgrade/downgrade` 往返 + JSON 读写往返进集成测试（0012 先例）。
- `tests/integration/test_db_migration.py`（需 TEST_DATABASE_URL）保持通过。
- world 夹具：显式 ensure_world + 播种实体/事件；时间冻结用注入 TimeProvider（不 monkeypatch datetime.now）。
