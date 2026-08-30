# V7.8 Persistence 设计

> 四张新表 + 配置组 + 保留策略。既有 12 张表零改动（evaluation_reports 仅 meta 补一个 JSON 键）。

## 1. 数据分类

| 类别 | 内容 | 寿命 | 采集纪律 |
|---|---|---|---|
| Runtime Debug Data | `runtime_traces`、`prompt_snapshots`、`decision_records` | 短（7d / 3d / 14d） | 采样 + error 必存 + 有界截断 |
| Production Metrics | `llm_call_records`（30d）；P2 可选 `metrics_snapshots`（90d） | 长 | 行小全量记（llm），或周期聚合（snapshots） |
| Evaluation Data | `evaluation_reports`（V7.5 既有，30d） | 不变 | V7.8 零改动 |

TTL 差异体现价值密度：prompt 最贵最敏感（3 天），trace 中等（7 天），决策记录最少但解释力最强（14 天），LLM 数值行小且是指标原料（30 天）。

## 2. 表结构（迁移 0013~0016）

全部遵循现有惯例：复数 snake_case 表名、`ck_/idx_` 前缀、JSON 列承载复合结构、ORM 集中在 `app/core/db.py`。

### 0013 runtime_traces

```sql
CREATE TABLE runtime_traces (
    id             VARCHAR PRIMARY KEY,          -- = request_id
    kind           VARCHAR NOT NULL,             -- turn / proactive / autonomy_tick（ck 约束）
    user_id        INTEGER NOT NULL,
    conversation_id VARCHAR,
    turn_id        VARCHAR,                      -- 关联主键
    action_id      VARCHAR,
    status         VARCHAR NOT NULL,             -- complete / degraded / error
    started_at     TIMESTAMPTZ NOT NULL,
    duration_ms    INTEGER,
    steps          JSONB NOT NULL DEFAULT '[]',
    events         JSONB NOT NULL DEFAULT '[]',
    token_usage    JSONB NOT NULL DEFAULT '{}',
    model_name     VARCHAR,
    meta           JSONB NOT NULL DEFAULT '{}',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_runtime_traces_turn (turn_id);
CREATE INDEX idx_runtime_traces_user_time (user_id, created_at);
CREATE INDEX idx_runtime_traces_conversation (conversation_id, created_at);
```

### 0014 llm_call_records

```sql
CREATE TABLE llm_call_records (
    id             VARCHAR PRIMARY KEY,
    request_id     VARCHAR,
    turn_id        VARCHAR,
    call_site      VARCHAR NOT NULL,             -- ck 枚举（与 prompt_snapshots 同表可 join 的枚举域）
    profile_id     VARCHAR,
    model          VARCHAR,
    provider       VARCHAR,
    status         VARCHAR NOT NULL,             -- ok / error
    latency_ms     INTEGER,
    ttft_ms        INTEGER,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    cost_estimate  DOUBLE PRECISION,
    error_kind     VARCHAR,
    started_at     TIMESTAMPTZ NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_llm_calls_request (request_id);
CREATE INDEX idx_llm_calls_turn (turn_id);
CREATE INDEX idx_llm_calls_time (created_at);
```

### 0015 prompt_snapshots

```sql
CREATE TABLE prompt_snapshots (
    id             VARCHAR PRIMARY KEY,
    request_id     VARCHAR NOT NULL,
    turn_id        VARCHAR,
    call_site      VARCHAR NOT NULL,
    profile_id     VARCHAR,
    model          VARCHAR,
    messages       JSONB NOT NULL,
    section_budget JSONB,
    truncated      BOOLEAN NOT NULL DEFAULT false,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_prompt_snapshots_turn (turn_id);
CREATE INDEX idx_prompt_snapshots_time (created_at);
```

### 0016 decision_records

```sql
CREATE TABLE decision_records (
    id             VARCHAR PRIMARY KEY,
    kind           VARCHAR NOT NULL,             -- ck 枚举
    request_id     VARCHAR,
    user_id        INTEGER NOT NULL,
    conversation_id VARCHAR,
    action_id      VARCHAR,
    trigger        VARCHAR,
    input_snapshot JSONB NOT NULL DEFAULT '{}',
    decision       VARCHAR NOT NULL,
    reason         VARCHAR NOT NULL,
    confidence     DOUBLE PRECISION,
    outcome        VARCHAR,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- outcome 幂等补写：UPDATE ... SET outcome WHERE id= AND outcome IS NULL
    CONSTRAINT ck_decision_records_kind CHECK (kind IN ('proactive_autonomy','turn_goal','turn_intention','turn_behavior'))
);
CREATE INDEX idx_decision_records_user_time (user_id, kind, created_at);
CREATE INDEX idx_decision_records_action (action_id);
```

各表 JSON 内容一律受域模型有界规则约束（截断在构造时完成，仓储不做二次裁剪）。

## 3. 保留策略与清理

- 沿用 V7.5 惰性清理先例：各仓储提供 `prune_before(cutoff)`，删除由**低频清理循环**驱动（lifespan 常驻 task，每日一次，串行跑四张表），不挂在写路径上。
- 单表单批上限 + 循环让步（避免长事务锁表）；清理失败只 log，下轮再清。
- 容量兜底：四表各自配置 `*_retention_days`；`runtime_traces` 额外受 trace 采样率控制写入速率。

## 4. 隐私与体积

- **prompt 主体**：默认 sampled 0.2 + 20000 字符上限 + 3 天 TTL；可选 `observability_prompt_redact=true` 时用户消息内容按 `content_preview`（`app/core/logutils.py` 既有工具）脱敏为摘要——本地单用户调试台默认不脱敏，外发/共享环境必须开启。
- **估算体积**（单机调试台量级）：每 turn ≈ trace 4KB + llm 行 5×300B + prompt（采样后均摊）~1.6KB ≈ 6KB/turn；万 turn/月 ≈ 60MB/月，四表 TTL 后稳态 < 100MB。
- 观测表不存：完整用户消息历史（trace extra 与 input_snapshot 均有界）、judge prompt 原文、API key 类配置。

## 5. 配置组（`app/core/settings.py`，沿用 evaluation_* 惯例）

```text
observability_persist_enabled            true    总开关（false = 回到 V7.5 行为）
observability_trace_sample_rate          1.0     trace 落库采样（error 恒必存）
observability_prompt_capture_mode        sampled disabled / sampled / always
observability_prompt_sample_rate         0.2
observability_prompt_max_chars           20000
observability_step_extra_max_chars       2000    step.extra / event.payload / input_snapshot 共用上限
observability_prompt_redact              false
observability_llm_cost_json              "{}"
observability_trace_retention_days       7
observability_prompt_retention_days      3
observability_decision_retention_days    14
observability_llm_call_retention_days    30
observability_cleanup_interval_hours     24
```

## 6. 测试与迁移纪律

- 每个迁移 task 验证 `alembic upgrade/downgrade` 往返 + JSON 列读写往返（V7.5-002 先例）。
- `tests/integration/test_db_migration.py`（需 `TEST_DATABASE_URL`）保持通过。
- 测试默认 `OBSERVABILITY_PERSIST_ENABLED=false`（conftest setdefault）；需要写库的测试 `override_settings` 显式开启，StaticPool 后台任务等待沿用现有 teardown 机制。
