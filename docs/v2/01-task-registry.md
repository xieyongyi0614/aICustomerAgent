# V2 开发任务注册表（01-task-registry）

> 输入来源：`docs/v2/v2-architecture.md`（Character State System 设计）
> 输出用途：可直接交给 Coding Agent 逐 Task 执行。
> 本文件为 V2 唯一任务入口，`tasks/` 目录下每个文件对应一个 Task（DOC-01 已随设计文档完成，不建文件）。

> **断点状态（2026-08-24）**：V2 全部 10 个任务已完成并通过验收（120 tests 全绿，pylint 7.98）。
> 断点标记：git tag `v2-checkpoint`（指向本提交）。
> 遗留项：全量测试偶发 1 个 teardown error（断言全过，原因待排查）；backend README 数据库章节仍写 SQLite，待更新。

---

## 1. 任务拆分原则

一个 Task 必须满足：

- 只有一个明确目标
- 可以独立开发
- 可以独立测试
- 可以独立验收
- 有明确输入 / 输出
- 有明确依赖关系

**禁止**出现"完成状态系统"这类过大粒度任务。

## 2. 任务类型（Type）

| 类型 | 含义 |
|---|---|
| BE | 后端业务逻辑（模型、规则、链、编排、Prompt） |
| DB | 数据访问 / 存储 |
| TEST | 测试 |
| DOC | 文档 |

## 3. 任务层级

```
Module（模块）
 ↓
Feature（功能点）
 ↓
Task（Task ID，见下表；详情见 tasks/ 各文件）
 ↓
Subtask（见各 Task 文件内"Subtask 拆分"）
```

---

## 4. 模块 / Feature / Task 结构总览

### 模块一：状态领域模型（Domain Models）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| V2 模型 | BE-01 | 状态领域模型（behavior / emotion / character_state / relationship） | P0 |

### 模块二：数据访问层（Repositories）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| 数据库切换 | DB-00 | PostgreSQL 切换与 Alembic 迁移体系 | P0 |
| 状态三表 | DB-01 | 三张状态表 ORM 与三个 repository | P0 |

### 模块三：状态规则与链（Rules & Chains）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| 规则引擎 | BE-02 | state_engine 确定性规则（纯函数） | P0 |
| 轮次分析链 | BE-03 | turn_analysis_chain（情绪 + 事件 + 行为） | P0 |
| 状态更新链 | BE-04 | state_update_chain（mood / inner_state / topic） | P0 |

### 模块四：Prompt 与编排（Prompt & Orchestration）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| Prompt 升级 | BE-05 | 行为指令资产 + PromptBuilder 三新 section | P0 |
| 预侧编排 | BE-06 | context_builder 扩展 + stream_chat 并发编排 | P0 |
| 后处理落库 | BE-07 | _post_process 状态更新与 emotion_history | P0 |

### 模块五：测试（Testing）

| Feature | Task ID | Task 名称 | 优先级 |
|---|---|---|---|
| 集成测试 | TEST-01 | 多轮状态演化端到端 + HTTP 集成 | P0 |

### 模块六：文档

| Feature | Task ID | Task 名称 | 优先级 | 状态 |
|---|---|---|---|---|
| V2 文档 | DOC-01 | 架构文档 + 本注册表 | P0 | ✅ 已完成 |

## 5. 总体依赖 DAG

```
DB-00（PostgreSQL 切换 + Alembic，仅依赖 V1 现状，可与 BE-01 并行）

BE-01（领域模型）
 │
 ├─→ DB-01（三表 + 三仓储，还需 DB-00 迁移体系）─→ BE-02（规则引擎，还需 settings 阈值）
 │
 ├─→ BE-03（轮次分析链，还需 V1 conftest FakeLLM）
 ├─→ BE-04（状态更新链）
 └─→ BE-05（行为资产 + PromptBuilder，还需 BE-01 的 TurnAnalysis 类型）

BE-02 + BE-03 + BE-05 ─→ BE-06（context_builder + stream_chat 编排接入，还需 DB-01）
BE-04 + BE-06 ─────────→ BE-07（后处理落库，还需 state_service）
BE-07 ─────────────────→ TEST-01（多轮状态演化集成测试）
```

### 并行化建议

- 分支 A0：`DB-00`（只动 `core/db.py` + settings + migrations，与 BE-01 无依赖，可最先启动）
- 分支 A：`BE-01 → DB-01 → BE-02`（基础串；DB-01 须等 DB-00 完成）
- 分支 B：`BE-01 → BE-03` 与 `BE-01 → BE-04`（两条链可并行）
- 分支 C：`BE-01 → BE-05`（纯资产 + Builder，可并行）

`BE-06` / `BE-07` 是收敛节点，须等全部前置完成。

## 6. 优先级说明

| 优先级 | 定义 | 范围 |
|---|---|---|
| **P0** | V2 必须完成 | 全部 10 个实施任务（含 DB-00 数据库切换） |
| **P1** | 无 | — |
| **P2** | 后续版本 | 见架构文档第 10 节 backlog（状态调试 API、并发覆盖、时间衰减曲线等） |

## 7. 执行顺序建议（按队列）

```
队列 1（可并行）：BE-01、DB-00
队列 2（可并行）：{DB-01 → BE-02}、{BE-03}、{BE-04}、{BE-05}
队列 3：BE-06
队列 4：BE-07
队列 5：TEST-01（回归全量 pytest）
```

## 8. 工程约束提醒（来自 AGENTS.md，实施时逐条遵守）

- 依赖方向单向：`api → services → repositories → core`；`models / prompts / character` 为共享支撑层
- LLM 只能来自 `llm_factory.get_llm()` 或请求级注入参数，链内 `(llm or get_llm())` 兜底
- DB 访问只走 repositories，业务层禁止直接 ORM
- 阈值 / 环境参数必须进 `core/settings.py`（delta 映射表例外，见架构文档 D3 决策）
- 读取进链、写入出链：状态写入只发生在 `_post_process`
- Prompt 组装必须走 `PromptBuilder`，禁止手工拼接
- 不添加代码注释，用命名表达意图
- 测试禁止真实 LLM 调用（FakeLLM 注入）；单元测试用内存 SQLite，HTTP / e2e 集成测试连 PostgreSQL（`alembic upgrade head` 建表）
- 数据库结构变更只走 Alembic revision（autogenerate + 人工审阅），`create_all` 已退役（单元测试内存建表属豁免）
- 只有用户明确要求时才提交 / 推送 / 建 PR

---

## 9. 目录结构

```
docs/v2/
├── 01-task-registry.md      # 本注册表（V2 唯一任务入口）
├── v2-architecture.md       # V2 架构总设计（任务输入依据）
└── tasks/
    ├── BE-01-state-models.md
    ├── DB-00-postgres-migration.md
    ├── DB-01-state-tables.md
    ├── BE-02-state-engine.md
    ├── BE-03-turn-analysis-chain.md
    ├── BE-04-state-update-chain.md
    ├── BE-05-prompt-builder-v2.md
    ├── BE-06-orchestration.md
    ├── BE-07-state-persistence.md
    └── TEST-01-state-e2e.md
```
