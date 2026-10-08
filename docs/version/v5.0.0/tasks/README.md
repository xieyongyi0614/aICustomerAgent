# V5.0.0 Task Detail 体例与撰写规范

> **上位文档（按优先级）**：`docs/version/v5.0.0/requirements-analysis.md`（需求与 11 条决策）→ `docs/version/v5.0.0/tasks.md`（任务注册表 + 七条前提）→ `docs/version/v5.0.0/traceability.md`（设计稿 119 条要求的覆盖矩阵）→ `docs/version/v5.0.0/flutter-architecture.md`（客户端技术方案）。
> **体例来源**：`docs/version/v4.0.0/tasks/PLA-001.md`（后端）、`PLA-016.md`（前端/客户端）。
> **本目录**：Task Detail 与 `tasks.md` 的注册区块一一对应，**不增不减**。§1 任务总览对应 41 份（2026-09-23 生成）；V5.1 增量（`tasks.md` §15）24 份；免商店自动更新（`tasks.md` §18，2026-10-08）3 份。

---

## 1. 文件命名

| 任务线 | 文件名 | 数量 |
|---|---|---|
| 客户端（Flutter，`apps/mobile/`） | `APP-001.md` ~ `APP-025.md` | 25 |
| 后端补齐（`apps/backend/`） | `API-001.md` ~ `API-010.md` | 10 |
| 平台横切（工程 / 合规 / 测试） | `PLT-001.md` ~ `PLT-006.md` | 6 |
| V5.1 增量（`tasks.md` §15） | `APP-027.md` ~ `APP-043.md`（17）；`API-015.md` ~ `API-020.md`（6）；`PLT-007.md`（1） | 24 |
| 免商店自动更新（`tasks.md` §18，2026-10-08） | `APP-044.md`；`API-022.md`；`PLT-008.md` | 3 |

> **增量注册体例**：`tasks.md` §12~§14、§16、§17 为「从简体例」（不另立 Detail），本目录**不为它们建文件**；上表第 4 行的 V5.1 与第 5 行的更新域**已有 Detail**，故登记在此。
> **编号避坑**：`API-021` 属 `tasks.md` §16（首页每日 AI 总结生成器，从简体例、无 Detail），**不是**更新域任务；更新域的后端任务是 **`API-022`**。

---

## 2. 统一章节体例（10 节，缺一节即不合格）

```text
# <ID> <English Task Name>

> **上游**：tasks.md 的该任务条目 · requirements-analysis.md 的相关 REQ · traceability.md 的来源条目
> **状态**：Task Detail（可执行；**未开工**）
> **归属层**：apps/mobile（Flutter）/ apps/backend（Python）/ 横切
> **里程碑**：M0~M4 / PLT · **批次**：任务线内的顺序 · **依赖**：<ID 列表>

## 1. Task Overview        —— 表格：Task ID / Task Name / Type / Priority / Objective / 交付面 / Dependencies / 新增设置 / 完成判据
## 2. Background            —— 现状证据（带文件路径与行号）+ 为什么必须做 + 在 V5.0.0 中的位置
## 3. Scope                 —— 3.1 In Scope（编号列表）/ 3.2 Out of Scope（明确禁止扩张，逐条给理由）
## 4. Technical Design Requirements
   ### 4.1 接口契约 / 组件契约  —— 字段表、事件 schema、组件尺寸表、页面信息流（**只写契约，不写代码**）
   ### 4.2 关键裁决          —— 表格：D# / 裁决 / 理由
   ### 4.3 数据流            —— 文本流程图（谁调谁、经哪一层）
   ### 4.4 依赖与边界        —— 允许依赖 / 禁止依赖
## 5. Implementation Plan   —— 有序步骤，每步一个可验证产出
## 6. File Impact           —— 6.1 新增 / 6.2 修改 / 6.3 禁止修改（本任务红线）
## 7. Testing Requirements  —— 用例表：用例名 + 断言（用例名用 snake_case，可执行语义）
## 8. Acceptance Criteria   —— 表格：AC# / 判据 / 验证方式（**每条必须可判定**）
## 9. Commit Requirement    —— 提交前命令块（含零回归 / 零改动核验）+ 提交信息
## 10. 需求溯源             —— 表格：设计稿条目（§编号 + 原型 #锚点）/ REQ / 覆盖状态
```

### 2.1 每节的硬要求

| 节 | 硬要求 |
|---|---|
| 1 | `完成判据` 必须是一条**可执行的判定**，不是「完成即算」 |
| 2 | 每条现状断言**必须带证据路径**（`文件:行号`），不得写「目前不支持」这类无出处结论 |
| 3.2 | Out of Scope 是**反范围护栏**，至少 5 条，且每条给理由；不得留空 |
| 4.1 | 后端写**字段级契约**；客户端写**组件尺寸/层级/文案**（取自设计系统 skill，不得自创） |
| 4.2 | 裁决表每行必须给理由，禁止只写结论 |
| 6.3 | 红线必须点名具体路径，便于 `git diff` 核验 |
| 7 | 每条用例给出**断言**，禁止只写「测试通过」 |
| 8 | 判据要能被 `git diff` / 命令输出 / 截图三种方式之一验证 |
| 10 | 必须能在 `traceability.md` 中找到对应行；找不到说明任务凭空发明，须回改 |

---

## 3. 三条任务线的差异化要求

### 3.1 `APP-*`（客户端）

- **必须先读** `.agents/skills/zhaoxi-design-system/SKILL.md` 及其 `references/`（tokens / components / orb / principles / flutter-mapping）——它是 UI 唯一真源，**优先级高于设计稿与原型**。
- 4.1 节写**组件契约**时，必须引用 skill 里的组件编号（`A2 ai-card` / `A14 proc` / `A9 tabbar` …）与页面结构编号（`B1 #home` / `B2 #chat` …）。
- 文案**必须沿用 skill `principles.md` §5.3 的范例文案**，不得自创风格。
- 验收必须含设计系统的**红线自检**（无硬编码色值 / 渐变只用于 AI / 动效 ≤ 400ms / 数字等宽 / M3 无漏出）。
- 测试要区分四层：单元 / golden / widget / 契约回放（见 `flutter-architecture.md` §8）。

### 3.2 `API-*`（后端补齐）

- 4.1 节写**字段级契约**（请求参数、响应字段、事件 schema、缺省语义）。
- 必须逐条过 `tasks.md` §10 的**铁律对齐检查表**，并在 4.2 节以表格形式留痕。
- 涉及新事件 → 登记 `tests/v30/runtime_contracts.py::EXPECTED_EVENT_TYPES`；涉及 `runtime_*` 字段 → 登记 `tests/v30/runtime_support.py::V30_RUNTIME_FIELDS`。
- 涉及迁移 → 写明链尾、`create_check_constraint` 完整布尔式、钉测升级清单（`SCHEMA_TABLE_COUNT` / `MIGRATION_HEAD` / 用例名）。
- 验收必须含**零回归（基线对照法）**与**零 `app/repositories` 反向依赖**两项硬项。
- 测试分三层：Focused → Module → 基线对照。

### 3.3 `PLT-*`（平台横切）

- 交付物可能是**结论报告 / 配置 / 流水线 / 规范**，不是代码，因此 6. File Impact 允许写「产出文档路径」。
- 必须明确**谁消费它的产出**（例如 `PLT-001` 的结论决定 M4 排期与 `APP-014` 三宫格形态）。
- 验收必须可复现（命令、测量方法、判定阈值），禁止主观判断。

---

## 4. 全局约束速查（所有任务共用）

| # | 约束 | 违反后果 |
|---|---|---|
| 1 | 新增 API **零** `app/repositories` 依赖 | 扩大 V4.0.0 已记 L3 债 |
| 2 | 不新增 `*_enabled` 功能开关；新设置只许**参数类**字段；env 名 = 字段名大写 | 违反 V4.0.0 裁决 9；`extra="ignore"` 静默失效 |
| 3 | 新事件类型必须登记 `EXPECTED_EVENT_TYPES`（未知类型 fail-closed） | 契约测试转红 |
| 4 | **不得**给 `loop_runs.steps` 加键（`test_agent_loop_core.py` 断言键集完全相同） | C2 收口点阻塞 |
| 5 | 不直写 `world_*` / `memories` / `relationship_state` / `loop_runs` | 违反事件 SoT 铁律 |
| 6 | `services` **不得** import `app.application` | 分层倒置 |
| 7 | 客户端 `features/*` 不得互相 import；`design_system/` 不得 import `core/` 或 `features/` | 破坏 golden 可测性 |
| 8 | 不建第二套 Agent；新能力走 Profile 阶段 / 段本体 / Update-handoff / 域唯一写面 / 既有 trigger | 架构分叉 |
| 9 | 删除文件一律 `find <file> -delete`，**绝不用 `git rm`** | 曾致 365 文件级事故 |
| 10 | 提交后**必须**复核 `git rev-parse HEAD` | 本机曾出现分支 ref 不更新 |
| 11 | 新建 `app/` / `tests/` 文件转 CRLF；`docs/**` 保持 LF | 巨型 diff |
| 12 | 零回归判据 = **当前失败集 ⊂ 基线失败集**（HEAD 基线本就不是绿的） | 误判回归 |

---

## 5. 撰写纪律

1. **不写代码、不写 DDL、不写 UI 稿**——只写契约、裁决、影响面、判据。
2. **不发明需求**：4.1 节的每一条都必须能在设计稿 / 原型 / 调研报告里找到出处（第 10 节负责举证）。
3. **不做范围蔓延**：M4（健康）与备忘录独立域已由决策 D1 / `APP-022` 降级裁决封口，不得在 Detail 里偷偷放回来。
4. **口径统一**：产品阶段一律写 **P1~P4**；仓库版本号写 `V4.0.0` / `V5.0.0`（决策 D10）。
5. **命名避歧**：用户健康数据域不得复用 `services/tool/health.py` 的「health」语义（那是工具熔断健康度）。
6. **不确定的地方显式写「待定 + 阻塞条件」**，不要用模糊措辞糊过去。
