# Persistence

> 报告存储（迁移 0012 + app/repositories/evaluation_repository.py，新增）：单表存三类评估产物，聚合视图按需派生不建表。**禁止保存完整 Prompt 与完整消息历史。**

## 1. 表结构（migration 0012，示意）

```python
# migrations/versions/0012_evaluation_reports.py（示意）
# 风格对齐 0011：合法值用 CheckConstraint 收敛，字符串列不带长度（与既有各表一致）
op.create_table(
    "evaluation_reports",
    sa.Column("id", sa.String, primary_key=True),              # uuid
    sa.Column("subject", sa.String, nullable=False),           # turn / proactive_action / offline_batch
    sa.Column("subject_id", sa.String, nullable=False),        # turn_id / action_id / run_id
    sa.Column("session_id", sa.String, nullable=True),         # 会话级过滤；offline_batch 为 NULL
    sa.Column("user_id", sa.String, nullable=False),
    sa.Column("character_id", sa.String, nullable=False, server_default="asuna"),
    sa.Column("overall_score", sa.Float, nullable=True),       # offline_batch 为 NULL
    sa.Column("verdict", sa.String, nullable=False),           # pass / warn / fail
    sa.Column("scores", sa.JSON, nullable=False),              # {dimension: {score, rule, judge, codes}}
    sa.Column("issues", sa.JSON, nullable=False),              # [{code, severity, dimension, message, evidence}]
    sa.Column("context_digest", sa.JSON, nullable=False),      # 有界摘要，≤2000 字符预算
    sa.Column("meta", sa.JSON, nullable=False),                # model_name / judge_used / fidelity / duration_ms
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.CheckConstraint(
        "subject IN ('turn', 'proactive_action', 'offline_batch')",
        name="ck_evaluation_reports_subject",
    ),
    sa.CheckConstraint(
        "verdict IN ('pass', 'warn', 'fail')",
        name="ck_evaluation_reports_verdict",
    ),
)
op.create_index("idx_evaluation_user_time", "evaluation_reports", ["user_id", "created_at"])
op.create_index("idx_evaluation_subject", "evaluation_reports", ["subject", "subject_id"])
```

设计约束：

- scores / issues / digest 用 JSON 而非展开列——评估 schema 处于观测迭代期（编码表会增删），结构化列会把每次迭代变成迁移；稳定后再考虑展开。
- `subject_id` 不做外键：报告生命周期（30 天）独立于消息 / 动作行，外键会把保留策略耦合进核心数据。
- 与 `proactive_actions` 迁移（0011）同风格：CHECK/ENUM 收敛合法值，索引按查询路径建。

## 2. 不存什么（数据膨胀负面清单）

| 禁存 | 理由 |
|---|---|
| judge 完整 prompt / 角色资产快照 | 角色资产在代码里，可按 version 重放；存副本只膨胀 |
| 完整消息历史 | digest 已含判定所需最小集（6 条 × 120 字符） |
| judge 原始自由文本输出 | judge 无自由文本通道（code 枚举 + evidence ≤80 字符） |
| 每条规则的中间计算过程 | 只存结论（issue），过程可由 digest + 规则代码重放 |

报告单行体积上限 ≈ digest 2000 字符 + issues 数十字节级——按 30 天保留期与当前对话量，属可忽略量级；若未来采样率与流量放大，先调 retention，不先改 schema。

## 3. 三种评估范围的存储映射

| 范围 | subject | subject_id | overall_score | 产生方式 |
|---|---|---|---|---|
| Conversation Evaluation | turn | turn_id | 按 turn 权重表 | post_process 第 7 步 |
| Character（主动行为）Evaluation | proactive_action | action_id | 按 proactive 权重表 | executor delivered 后 |
| Regression Evaluation | offline_batch | run_id（uuid） | NULL（只出统计） | offline evaluator |

**Character / Regression 聚合不建表**：按 user_id + created_at 窗口实时聚合查询（均值、verdict 分布、issue 直方图）由 offline evaluator / 查询函数派生。理由：聚合是纯派生数据，物化它就要处理刷新与一致性——观测系统的正确姿势是**明细唯一事实源，视图随取随算**。聚合结果（含 run_id 清单）可作为 JSON 工件落测试输出目录，不入库。

turn / proactive_action 报告携带 `session_id`（取自 PostProcessContext / proactive action 的 session_id），**会话级过滤直接可用**——这是 "Conversation Evaluation" 范围的查询键；offline_batch 的 session_id 为 NULL，verdict 按 issues 映射（evaluation-model.md §2），overall_score 恒为 NULL。

## 4. Repository 接口

```python
# app/repositories/evaluation_repository.py
class EvaluationRepository:
    async def save(self, report: EvaluationReport) -> None
    async def get_by_subject(self, subject, subject_id) -> EvaluationReport | None
    async def list_by_user(self, user_id, limit=50, offset=0) -> list[EvaluationReport]
    async def prune_before(self, cutoff: datetime) -> int
```

- 遵循三层依赖：业务层只经此仓储访问报告表，禁止直连 ORM。
- 同一 subject 多次评估（重放 / 手动重评）：允许并存，查询口返回 created_at 最新一条；不做 upsert，保留历史便于对比。

## 5. 保留策略（惰性清理）

```text
每次 save 后顺手执行：prune_before(now - evaluation_retention_days)
```

沿用 V7 proactive_actions 24h 惰性过期的同款模式——不引入定时清理任务，成本摊进写入路径。retention 默认 30 天。

## 6. 查询路径（只读消费）

```text
GET /api/v1/debug/turns/{turn_id}/evaluation            → 单轮报告（无则 404，语义与 trace 端点一致）
GET /api/v1/debug/proactive/{action_id}/evaluation      → 主动行为报告
offline_evaluator 聚合函数                              → 窗口统计（不落库）
```

全部 debug 前缀、只读、无用户侧暴露（README 硬边界）。
