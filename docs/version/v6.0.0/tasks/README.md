# V6.0.0 Task Detail 体例与撰写规范

> **上位文档（按优先级）**：`docs/agent-evolution-plan-2026-10.md`（三方审核结论 + 分层演进设计）→ `docs/version/v6.0.0/tasks.md`（任务注册表 + 七条前提裁决）→ `docs/current-system-architecture-baseline.md`（现状唯一可信基线）→ `docs/version/v5.0.0/tasks.md` §0（迁移纪律与测试纪律）/ §0.4（全局约束）。
> **体例来源**：`docs/version/v5.0.0/tasks/README.md`（10 节体例）· `docs/version/v4.0.0/tasks/PLA-001.md`（后端撰写先例）· `docs/version/v5.0.0/tasks/API-007.md`（同为记忆域，最贴近的先例）。
> **本目录**：Task Detail 与 `tasks.md` 的注册区块一一对应，**不增不减**。当前已生成 **28 份**（2026-10-14）：M1（`MEV-001~004`）+ M2（`MEV-005~008`）+ M3（`MEV-009~014`）+ P1/P2（`PLN-001~009`）+ S（`SAG-000~004`）。
> **注**：`SAG-*` 的 Task Detail 已就位，但**任务本身仍未排期且阻塞于 `SAG-000` 的红线裁决**（`tasks.md` §0.6 裁决 6）——**Detail 就位不等于可开工**。

---

## 1. 文件命名

| 任务线 | 文件名 | 数量 | 状态 |
|---|---|---|---|
| 记忆演进（`apps/backend/app/services/memory/`） | `MEV-001.md` ~ `MEV-014.md` | 14 | **已生成（M1/M2/M3）** |
| 计划澄清（`apps/backend/app/services/goal/`） | `PLN-001.md` ~ `PLN-009.md` | 9 | **已生成（P1/P2）** |
| 子 Agent（未排期） | `SAG-000.md` ~ `SAG-004.md` | 5 | **已生成**（仍阻塞于 `SAG-000` 红线裁决） |

> **编号避歧**：`MEV-` / `PLN-` / `SAG-` 为本版本新启用前缀。**不得复用** `MEM-001~011`（V2.0.0 记忆域 Task Detail 已占用）、`PLAN-001~012`（V2.5.0 Planning System 已占用）、`LIFE-` / `REL-` / `DEV-` / `REF-` / `AUT-` / `RT-` / `PLA-` / `APP-` / `API-` / `PLT-`（均属其他版本线）。

---

## 2. 统一章节体例（10 节，缺一节即不合格）

```text
# <ID> <English Task Name>

> **上游**：tasks.md 的该任务条目 · agent-evolution-plan-2026-10.md 的对应章节 · current-system-architecture-baseline.md 的相关节
> **状态**：Task Detail（可执行；**未开工**）
> **归属层**：apps/backend（Python）· **里程碑**：M1~M3 / P1~P2 / S（未排期）· **批次**：任务线内顺序 · **依赖**：<ID 列表>

## 1. Task Overview        —— 表格：Task ID / Task Name / Type / Priority / Objective / 交付面 / Dependencies / 新增设置 / 完成判据
## 2. Background            —— 现状证据（文件:行号）+ 为什么必须做 + 在本版本中的位置
## 3. Scope                 —— 3.1 In Scope（编号列表）/ 3.2 Out of Scope（≥5 条，逐条给理由）
## 4. Technical Design Requirements
   ### 4.1 契约            —— 字段表 / 函数签名 / 枚举映射 / 缺省语义（**只写契约，不写代码**）
   ### 4.2 关键裁决        —— 表格：D# / 裁决 / 理由
   ### 4.3 数据流          —— 文本流程图（谁调谁、经哪一层、降级点在哪）
   ### 4.4 依赖与边界      —— 允许依赖 / 禁止依赖 / Preserve 断言 / 待定项
## 5. Implementation Plan   —— 有序步骤，每步一个可验证产出
## 6. File Impact           —— 6.1 新增 / 6.2 修改 / 6.3 禁止修改（本任务红线，点名路径）
## 7. Testing Requirements  —— 用例表（Focused / Module / 基线对照三层），用例名 snake_case + 断言
## 8. Acceptance Criteria   —— 表格：AC# / 判据 / 验证方式（每条可判定）
## 9. Commit Requirement    —— 提交前命令块（含零回归 / 零改动核验）+ 提交信息
## 10. 溯源                —— 表格：演进规划条目 / tasks.md 条目 / 覆盖状态
```

### 2.1 每节的硬要求

| 节 | 硬要求 |
|---|---|
| 1 | `完成判据` 必须是**可执行的判定**（命令输出 / 测试名 / diff 判定），不是「完成即算」 |
| 2 | 每条现状断言**必须带证据路径**（`文件:行号`），不得写「目前不支持」这类无出处结论 |
| 3.2 | Out of Scope 是**反范围护栏**，至少 5 条，每条给理由；不得留空 |
| 4.1 | 后端写**字段级契约**（函数签名 / 请求响应字段 / 枚举值域 / 缺省语义 / 失败语义） |
| 4.2 | 裁决表每行必须给理由，禁止只写结论 |
| 6.3 | 红线必须点名具体路径，便于 `git diff` 核验 |
| 7 | 每条用例给出**断言**，禁止只写「测试通过」 |
| 8 | 判据要能被 `git diff` / 命令输出 / 测试名三种方式之一验证 |
| 10 | 必须能回溯到 `docs/agent-evolution-plan-2026-10.md` 与 `docs/version/v6.0.0/tasks.md` 的具体章节 |

---

## 3. 三条任务线的差异化要求

### 3.1 `MEV-*`（记忆演进，后端域内扩展）

- **性质是 `Extend`，不是重构**：`services/memory/` 是记忆域**唯一写面**；新增能力必须落该单包内（或其新增模块），**不得**另起 `memory3/` 或第二套摄取/检索。
- **必须遵守记忆域三条既有纪律**：
  1. **降级不阻断**——任何新增链路异常只许回落既有路径 + 落 trace，绝不阻断对话或规划（先例：`services/memory/retriever.py:344-346` 的向量路 try/except、`:355-357` 的候选池 try/except）。
  2. **候选唯一入口**——写入一律经 `services/memory/ingest.py::create_candidate`（`:67`，文件内注明「禁止直写 memories」）；唯一既有例外是 `services/action/capabilities/memory.py` 的 `remember_fact`（`ingest.py:183-184` 已显式跳过防双写）。
  3. **打分权重全部从 settings 读**，禁止硬编码字面量（`services/memory/retriever.py` 现状：`:247-249` / `:252` / `:309` / `:311`）。
- **prompt 预算纪律**：注入总量受 `memory_retrieval_budget`（`core/settings/memory.py:51`，默认 800 字符）与 `context_total_char_budget`（`app/prompts/builder.py:301`）双重约束；新增能力必须在预算内竞争，不得单方面抬高预算。
- **涉及迁移的任务**（`MEV-005` / `MEV-009`）必须写明：链尾、`create_check_constraint` 完整布尔式、`tests/support/schema_pins.py` 升级清单（`MIGRATION_HEAD` / `MIGRATION_HEAD_PARENT` / `SCHEMA_TABLE_COUNT` / `SCHEMA_COLUMNS_DIGEST`）与受影响的钉测文件清单。
- **验收必须含**：零回归（基线对照法）+ 策略/取值位 `off` 时行为逐字节不变 + 降级路径可用。

### 3.2 `PLN-*`（计划澄清，`services/goal/` 域内扩展）

- **落点硬约束**：只许落 `apps/backend/app/services/goal/`；**禁止**向 `apps/backend/app/services/planning/` 加模块（包模块枚举断言 `tests/v25/test_plan002_static_scan.py:189-207` + 调用白名单 `services/planning/goal_contract.py:197`）。
- **零迁移优先**：`PLN-001~005` 必须复用 `validated` 停靠态 + `trigger_registry` 新 kind；**不新增 `GoalPlanStatus` 值、不新增表、不新增 `decision_records` kind**。
- 已生成：`PLN-001~009`（见 §1）。**落点修正已登记**：`PLN-006`（移动端卡片）依赖改为 **`PLN-007`**（客户端需结构化端点，而非对话轮次 `PLN-004`）；`PLN-003` 的挂起载体复用 `trigger_registry` 的 **`action_due` + `payload.kind`**（`ck_trigger_registry_type` 是 3 值 CHECK，新增值需迁移）并须**逐点排除**既有 `action_due` 消费路径。

### 3.3 `SAG-*`（子 Agent，**未排期**）

- **禁止开工**：前置 = `SAG-000` 红线裁决（`docs/agent-evolution-plan-2026-10.md` §4.2 RL-1~RL-5）+ 基线登记。裁决前任何 `SAG-*` 代码均判违规（`tasks.md` §0.6）。
- 已生成：`SAG-000~004`。其中 `SAG-000` 为**零代码的裁决任务**（产出裁决记录 + 基线三处更新）；`SAG-001~004` 的契约在 Detail 中**标注为「候选形态，待裁决冻结」**，不得据其先行实现。
- 迁移取号：`SAG-002` 承接 `0012`（`MEV-005`=`0010`、`MEV-009`=`0011`）。

---

## 4. 全局约束速查（所有任务共用，继承 `docs/version/v5.0.0/tasks/README.md` §4 并补本版本项）

| # | 约束 | 违反后果 |
|---|---|---|
| 1 | **不新增 `*_enabled` 功能开关**；新设置只许参数类 / 取值类 / 策略位（策略位命名对齐 `plan_require_approval` 先例）；env 名 = 字段名大写（无 alias 层） | 违反 V4.0.0 裁决 9；`extra="ignore"` 会导致静默失效 |
| 2 | 不建第二套 Agent / 不新增 Profile / 不改 `profiles.py` 阶段序列 | 架构分叉（基线 ADR-7） |
| 3 | 不直写 `memories` / `world_*` / `relationship_state` / `loop_runs` | 违反域唯一写面纪律 |
| 4 | `services/**` **不得** import `app.application` | 分层倒置 |
| 5 | 迁移**只能追加**（当前链尾 `0009`，本版本从 `0010` 起）；同一批迁移**串行入链**，不得并行改链尾 | 链断裂 / 钉测大面积转红 |
| 6 | 加迁移必须同步 `tests/support/schema_pins.py`（单点真源）并盘点受影响钉测 | `SCHEMA_COLUMNS_DIGEST` / `MIGRATION_HEAD` 断言转红 |
| 7 | `op.create_check_constraint` **必须传完整布尔式**（`f"col IN {target}"`），不能传值清单 | 曾致 PG `DatatypeMismatch` |
| 8 | 删除文件一律 `find <file> -delete`，**绝不用 `git rm`** | 曾致 `apps/backend/app/` 365 文件级事故 |
| 9 | 新建 `app/` / `tests/` 文件转 **CRLF**；`docs/**` 保持 LF | 巨型 diff |
| 10 | 测试内不要 `from app.core.db import SessionLocal`，用 `app.repositories.<x>_repository.SessionLocal`（autouse `_offline_repos` 已重定向） | 连到真实库 |
| 11 | 批量 pytest 加 `--basetemp=<每次换名的新目录>` + `-rf`；PG 用例前置 `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` | 统计行被吞 / 脏 schema |
| 12 | 零回归判据 = **当前失败集 ⊂ 基线失败集**（HEAD 基线本就不是全绿，`docs/version/v5.0.0/tasks.md:50`） | 误判回归 |
| 13 | 提交后**必须**复核 `git rev-parse HEAD` | 本机曾出现分支 ref 不更新 |
| 14 | 不写代码 / DDL / UI 稿进 `docs/**`；不发明需求 | 文档与实现脱节 |

---

## 5. 撰写纪律

1. **不写代码、不写 DDL、不写 UI 稿**——只写契约、裁决、影响面、判据。
2. **不发明需求**：`3.1 In Scope` 的每一条都必须能在 `docs/agent-evolution-plan-2026-10.md` 或 `docs/version/v6.0.0/tasks.md` 找到出处（第 10 节负责举证）。
3. **不做范围蔓延**：M3（图谱与产品面）、P（计划澄清）、S（子 Agent）的能力**不得**放进 M1/M2 的 Detail。
4. **口径统一**：里程碑一律写 `M1~M3` / `P1~P2` / `S`；仓库版本号写 `V6.0.0`。
5. **命名避歧**：记忆域「类型（`type`）」与「通道（`layer`）」是两个正交维度，禁止混用；`layer` 只作检索分通道依据，**不做权限或来源真相**（来源真相永远是 `source_ref` + `memory_candidates`）。
6. **不确定的地方显式写「待定 + 阻塞条件」**，不要用模糊措辞糊过去。
