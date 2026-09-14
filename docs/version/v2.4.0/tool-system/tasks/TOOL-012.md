# TOOL-012 Task Detail — 系统验收与回归清单

> 上游：[../architecture.md](../architecture.md) §11.4（版本验收 Gate）、§9.5（安全不变量）、§9.1（Non-Goals）；[../tasks.md](../tasks.md) TOOL-012
> 状态：设计稿（未实现）
> 范围红线：**只做验收，不新增功能**；期望值全部取自已实现代码；Flag 全 off 时必须与 V2.3.0 逐字节一致；不碰 git（提交由用户决定）。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-012 |
| **Task Name** | 系统验收与回归清单 |
| **Priority** | P0（但必须最后执行） |
| **Dependencies** | TOOL-001 ~ TOOL-011 |
| **建议提交** | `docs: V2.4.0 工具系统验收与回归清单` |

## 1.1 Goal

交付**版本级验收**。把 architecture 定义的八个版本 Gate 转化为可执行的判定，交付端到端场景集、Flag 矩阵一致性测试与人工回归清单，并验证三禁令（不破坏 Agent / Memory / Session / Event）与十条安全不变量。

本任务是版本的**出口判定**——它不产出新功能，只回答一个问题："V2.4.0 能不能上线？"

## 1.2 Scope

**包含**

- 新增 `tests/v24/test_tool_acceptance.py`：Flag 矩阵 + 逐字节一致性 + 端到端场景。
- 新增 `docs/version/v2.4.0/tool-system/scenario-test.md`：场景用例（用户故事层）。
- 新增 `docs/version/v2.4.0/tool-system/regression-checklist.md`：人工回归条目。
- 八个版本 Gate 的可执行判定（§2.2）。
- 三禁令验证（静态 + 运行期）。
- 十条安全不变量验证。
- 零迁移断言的最终核对（含 TOOL-005 Q2 裁决结论的落定）。
- `.env.example` 补 v24 Flag / 参数段。

**不包含（Non-Scope）**

- 任何功能实现或缺陷修复（发现问题回归对应任务修）。
- 真实模型人工回归的执行（属上线前流程，本任务只交付清单）。
- 前端面板（本版本无前端改动需求；若需可对齐 WS-018 风格另开任务）。
- git 提交 / 推送 / PR（由用户决定）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 |
|---|---|---|
| `tests/v24/test_tool_acceptance.py` | 新增 | Flag 矩阵、逐字节一致性、端到端场景、不变量断言 |
| `docs/version/v2.4.0/tool-system/scenario-test.md` | 新增 | 用户故事层场景用例 |
| `docs/version/v2.4.0/tool-system/regression-checklist.md` | 新增 | 人工回归条目 |
| `.env.example` | 扩展 | v24 Flag 与参数段 |

**验收双层结构**

```text
第一层｜自动化（结构 + 不变量）
   test_tool_acceptance.py
     ├─ Flag 矩阵：总闸 × 10 子闸的启用链与行为分支
     ├─ 逐字节一致性：Flag 全 off vs V2.3.0 基线
     ├─ 静态扫描：写域护栏 / 依赖方向 / 零迁移 / 凭据零硬编码
     └─ 十条安全不变量断言

第二层｜场景（行为）
   scenario-test.md
     ├─ 按用户故事组织（"用户让我明天提醒他"）
     ├─ 每条含 Preconditions / Input / Flow / Expected / Related Modules
     └─ 期望值取自已实现代码，不臆造

第三层｜人工回归
   regression-checklist.md
     ├─ 真实模型下的端到端人工验证条目
     └─ 与双层形成互补，不重复断言
```

## 2.2 数据结构

### 八个版本 Gate（architecture §11.4）

| Gate | 判定内容 | 验证手段 |
|---|---|---|
| **G-COMPAT** | Flag 全 off：prompt 与 V2.3.0 逐字节一致；既有测试零修改通过；`ACTION_CAPABILITY_MAP` 原路径生效 | 自动化（prompt 快照 + 全量既有测试） |
| **G-GOVERN** | 每个工具可回答四问（谁注册 / 何时启用 / 当前状态 / 最近健康度） | 自动化（`describe` + `effective_status` + `health`） |
| **G-SELECT** | 同一意图在不同 Run Profile / 时机下选出不同工具或不同工具面 | 自动化（多组投影对照 + `surface_hash`） |
| **G-VALIDATE** | 参数错误在执行前拦下，且给出可读字段级理由 | 自动化（结构 8 类 + 语义 5 类） |
| **G-PERMISSION** | 默认拒绝生效；危险操作需确认；越权调用零外部调用 | 自动化（打桩断言外部调用为 0） |
| **G-WORLD** | 工具经 outbox 写世界；无工具直接 import 世界仓储 | 自动化（静态扫描 + 端到端） |
| **G-MEMORY** | 读类工具零沉淀；重要结果进候选；R1~R8 零豁免 | 自动化（零写入断言 + 政策拒收断言） |
| **G-EXTEND** | 新增内置工具 ≤ 4 步；新增外部 API 工具 ≤ 1 个 YAML | 半自动（diff 计数 + 实操记录） |

### Flag 矩阵

| 组 | 总闸 | 子闸组合 | 断言重点 |
|---|---|---|---|
| 1 | off | 全部 off | 与 V2.3.0 逐字节一致（基线） |
| 2 | on | 全部子闸 off | 注册表构建但四纪律不生效；行为接近 V9 |
| 3 | on | 仅 `schema_validation` | 校验生效，其余不生效 |
| 4 | on | 仅 `permission` | 授权闸生效，其余不生效 |
| 5 | on | 仅 `observation` | 结果归一 + 兼容双写生效 |
| 6 | on | 仅 `surface` | 工具面投影生效（前台） |
| 7 | on | 仅 `memory` | 记忆分层生效 |
| 8 | on | 仅 `reflection` | 反思证据窗生效 |
| 9 | on | 仅 `channel` | 通道工具可用（需 `feishu_enabled`） |
| 10 | on | 仅 `external_api` | 清单加载生效 |
| 11 | on | 仅 `user_defined` | 自定义注册可用 |
| 12 | on | 全部子闸 on | 全链行为 |
| 13 | off | 任一子闸 on | 启动 fail-fast（串行链校验） |

### 三禁令验证

| 禁令 | 验证手段 |
|---|---|
| 不新建第二套 Agent | 静态：无新 Run Profile / 无新阶段序列 / `profiles.py` 零 diff；运行期：Run 台账仍只有三种 `run_kind` |
| 不新建第二套 Memory | 静态：无新记忆表 / 无新记忆写入通道；运行期：`memories` 表写入全部经 `memory_policy` |
| 不新建第二套 Event System | 静态：无新事件表 / 无新事件总线；运行期：事件唯一 SoT 仍是 `world_events`，投递仍走 outbox / trigger_registry |
| （Session 系统） | 静态：`conversations` / `messages` 表零改动；无新会话存储 |

### 十条安全不变量（architecture §9.5）

| # | 不变量 | 验证 |
|---|---|---|
| 1 | 默认拒绝 | 无 grant 的 sensitive/dangerous 工具永不执行 |
| 2 | 零外部调用于闸门之前 | 权限/校验失败路径外部调用为 0（打桩） |
| 3 | 凭据零硬编码 | 静态扫描 + `.env.example` 检查 |
| 4 | 域名白名单 | 白名单外拒绝；空 = 全禁 |
| 5 | 参数脱敏 | sensitive 参数不进台账；`redacted` 记录 |
| 6 | 不可逆操作必审计 | dangerous 工具 `audit` 恒 True |
| 7 | 等级只升不降 | 命名空间下限生效；降级需 override reason |
| 8 | 不受信命名空间 | `user.*` / `ext.api.*` 默认 dangerous + 不沉淀 |
| 9 | 自我提权禁止 | 工具面内不存在"改权限"的工具（枚举断言） |
| 10 | 提示注入防线 | 外部内容打 `untrusted=True`；不作指令 |

## 2.3 核心流程

### 逐字节一致性验证

```text
基线准备
   git show <V2.3.0 标签>:app/prompts/... → 基线 prompt 快照
   （⚠ 只读，不覆盖工作区；用 git show 输出到临时文件比对）
        │
        ▼
Flag 全 off 下运行同一输入
   ├─ prompt 快照逐字节比对
   ├─ 维护步序列比对
   ├─ 行动域行为快照比对（steps 形状）
   └─ 全量既有测试运行（零修改）
```

**纪律（教训继承）**：不使用 `git show HEAD:file > file` 覆盖工作区文件；一律输出到临时路径比对。改迁移前先跑干净链（`@migration` 标记测试）。

### 零迁移最终核对

```text
① 迁移目录 diff：应为空（无新增迁移文件）
② 模型 diff：worlds / world_entities / world_events / world_snapshots /
             daily_plans / user_situations / action_records / memories /
             trigger_registry / channel_identities 全部零结构变更
③ TOOL-005 Q2 裁决结论落定：
   ├─ 若为方案 A（复用 JSON 载荷）→ 零迁移断言成立
   └─ 若为方案 B（扩列）→ 必须回写 architecture §5.1 与 tasks.md，
                          并在此记录"零迁移断言已修正"
```

### 端到端场景集

| 场景组 | 覆盖 |
|---|---|
| **S1 前台工具调用** | 用户消息 → 工具选择 → 执行 → 结果进回复（≥ 9 工具各一例） |
| **S2 参数校验** | 结构失败 8 类 + 语义失败 5 类各一例 |
| **S3 权限与确认** | 默认拒绝 / 首次确认 / TTL 复用 / 过期 / 否定（5 例） |
| **S4 自治调用** | 自治 tick → 工具面收窄 → 意图 → 执行 → 世界更新（三账对齐） |
| **S5 世界契约** | 工具经 outbox 写世界；直写被静态拦截（2 例） |
| **S6 记忆分层** | 读类零沉淀 / 重要结果沉淀 / R1~R8 拒收 / 幂等（4 例） |
| **S7 反思效能** | 失败证据 → 门槛 → Insight → 不熔断工具（2 例） |
| **S8 通道工具** | 发送需确认 → 切分不变式 → 错误映射（3 例） |
| **S9 扩展性** | 内置四步 / 外部一 YAML / DSL 负例（3 例） |
| **S10 多 tick 韧性** | 工具失败重试、熔断半开、长离线后自治（3 例） |

## 2.4 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `tests/conftest.py::_offline_repos` | 复用内存 SQLite 隔离；新增 service 模块须加入 `_SERVICE_DB_MODULES` | 增量（若新增模块级 SessionLocal） |
| V2.3.0 `test_ws019_acceptance.py` | 结构对齐（Flag 矩阵 + 逐字节一致性 + 不变量扫描的写法参照） | 零改动 |
| `docs/version/v2.3.0/regression-checklist.md` | 体例参照 | 零改动 |
| `docs/version/v2.3.0/scenario-test.md` | 体例参照（场景用例六段式） | 零改动 |
| 全量既有测试 | 零修改通过（G-COMPAT 硬要求） | 零改动 |

---

# 3. Database Changes

**本任务无任何数据库变更。**

| 项 | 结论 | 说明 |
|---|---|---|
| Table | 无新增 | 验收不产数据表 |
| Field | 无新增列 | — |
| Index | 无新增 | — |
| Migration | **无（且本任务的职责之一是证明全版本零迁移）** | 见 §2.3 零迁移最终核对 |

**本任务对迁移的职责**：不是"不产生迁移"，而是**证明整个 V2.4.0 没有产生迁移**。若核对发现迁移目录出现新增文件，本任务判定为失败，必须回溯定位是哪个任务违背了 architecture §5.1 裁决。

---

# 4. API / Interface Design

本任务不新增对外 API；"接口"为验收设施。

## 4.1 验收测试接口

```text
interface ToolAcceptanceSuite:
    run_flag_matrix() -> MatrixReport              # 13 组 Flag 组合
    run_bytewise_compat() -> CompatReport          # Flag 全 off vs V2.3.0
    run_end_to_end_scenarios() -> ScenarioReport   # S1~S10
    run_invariant_checks() -> InvariantReport      # 十条安全不变量
    run_ban_checks() -> BanReport                  # 三禁令
    run_gate_checks() -> GateReport                # 八个版本 Gate
```

| 项 | 内容 |
|---|---|
| **Input** | 环境（内存 SQLite + LLM stub + 通道 stub） |
| **Output** | 分类报告（通过 / 失败 / 跳过，含失败项定位） |
| **纪律** | 离线可跑（零真实 LLM、零真实网络、零真实通道） |

## 4.2 静态扫描接口

```text
interface ToolStaticScans:
    scan_world_write_guard() -> list[Violation]        # 工具实现体禁止写世界
    scan_dependency_direction() -> list[Violation]     # 模型层零仓储/服务依赖
    scan_credential_hardcode() -> list[Violation]      # 凭据零硬编码
    scan_forbidden_tables() -> list[Violation]         # 无新表/无新事件存储
    scan_no_second_runtime() -> list[Violation]        # 无新 Profile/新阶段序列
```

## 4.3 人工回归清单接口

```text
interface RegressionChecklist:
    sections() -> list[str]          # 按能力域分节
    items(section: str) -> list[dict]   # {id, precondition, steps, expected, related_task}
    mark(item_id: str, result: str, note: str) -> None
```

| 项 | 内容 |
|---|---|
| **Input** | 人工执行结果 |
| **Output** | 回填的清单状态 |
| **体例** | 对齐 V2.3.0 `regression-checklist.md` |

---

# 5. Implementation Plan

## Step 1 — Flag 矩阵与逐字节一致性

1. 实现 Flag 矩阵 13 组测试（总闸 × 子闸组合）。
2. 建立 V2.3.0 基线 prompt 快照（`git show` 输出到临时文件，**不覆盖工作区**）。
3. 实现逐字节一致性比对（prompt + 维护步序列 + 行动域行为快照）。
4. 运行全量既有测试，确认零修改通过。
5. 核对零迁移：迁移目录 diff 为空 + 模型 diff 为空 + 落定 TOOL-005 Q2 结论。

## Step 2 — 端到端场景与不变量

1. 实现 S1~S10 场景集（约 30 例），全部离线可跑（LLM stub + 通道 stub）。
2. 实现十条安全不变量断言（含"零外部调用"打桩与"自我提权禁止"枚举断言）。
3. 实现三禁令验证（静态 + 运行期）。
4. 实现八个版本 Gate 的自动化判定（G-EXTEND 为半自动：diff 计数 + 实操记录）。

## Step 3 — 文档交付与人工回归清单

1. 编写 `scenario-test.md`（用户故事层，六段式，期望值取自实现）。
2. 编写 `regression-checklist.md`（人工条目，按能力域分节）。
3. 补 `.env.example` v24 段（Flag + 参数，全部默认值，不含真实凭据）。
4. 交叉核对：文档中的每条期望值均可在代码中找到依据（避免臆造）。
5. 汇总验收报告：八个 Gate 判定 + 遗留问题（Q1~Q8）关闭状态。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- Flag 矩阵 13 组全部通过；第 13 组（子闸 on 而总闸 off）触发启动 fail-fast。
- **G-COMPAT**：Flag 全 off 时 prompt 逐字节一致、维护步序列一致、行动域行为快照一致；既有测试零修改通过。
- **G-GOVERN**：每个工具可回答四问（注册来源 / 启用时点 / 当前状态 / 最近健康度）。
- **G-SELECT**：≥ 3 组不同语境下投影出不同工具面，`surface_hash` 可复现。
- **G-VALIDATE**：结构 8 类 + 语义 5 类校验失败各有用例，均含字段级可读理由。
- **G-PERMISSION**：默认拒绝全路径通过；越权调用外部调用数为 0（打桩断言）。
- **G-WORLD**：静态扫描零违规；端到端工具写世界全部经 outbox。
- **G-MEMORY**：读类工具零写入；政策拒收候选被丢弃；R1~R8 零豁免。
- **G-EXTEND**：新增内置工具 ≤ 4 步（diff 计数）；新增外部 API 工具 ≤ 1 个 YAML（实操记录）。

## 6.2 Integration Acceptance

- 三禁令验证全部通过：无第二套 Agent / Memory / Event（含 Session 存储）。
- 十条安全不变量各有断言且全部通过。
- 零迁移核对通过：迁移目录 diff 为空、模型 diff 为空；TOOL-005 Q2 结论已落定并留痕。
- 场景集 S1~S10（约 30 例）全部离线可跑（零真实 LLM / 网络 / 通道）。
- `regression-checklist.md` 与 `scenario-test.md` 与自动化测试形成**互补而非重复**（断言不重叠）。
- 文档中每条期望值均可在代码中找到依据（无臆造期望）。
- `.env.example` 补齐 v24 段且不含真实凭据。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | 基线 prompt 快照获取时工作区有未提交改动 | 用 `git show` 输出到临时文件比对，**不覆盖工作区**（教训继承） |
| E2 | 迁移链在 SQLite 上跑 `@migration` 往返测试 | 全通（若失败须先修迁移再继续验收） |
| E3 | 某场景需真实 LLM 才能判定 | 标为"人工回归条目"移入 checklist，不放入自动化场景集 |
| E4 | 静态扫描误报（如测试文件中的违规示例） | 扫描范围限定为生产代码路径；测试内的负例样本显式排除 |
| E5 | 通道 stub 未覆盖某 `ChannelErrorKind` | 该映射行标为人工回归条目，自动化只覆盖可 stub 的 kind |
| E6 | Flag 矩阵某组合行为未定义（如仅 `channel` on 而 `feishu_enabled` off） | 按串行链校验 fail-fast 或明确降级，测试覆盖该分支 |
| E7 | 零迁移核对发现新增迁移文件 | 验收失败，回溯定位违背任务并修正（不得直接接受） |
| E8 | 既有测试中已存在的存量失败 | 用 V2.3.0 基线证明为存量失败后单列记录，不计入本版本回归 |
| E9 | 场景期望值与实现不符 | 以**实现为准**修正文档（若实现确有缺陷则回归对应任务修） |
| E10 | TOOL-005 Q2 裁决为方案 B（扩列） | 回写 architecture §5.1 与 tasks.md，并在验收报告中显式记录"零迁移断言已修正" |
| E11 | 多用户并发场景下的工具面一致性 | 投影为纯函数无共享状态，并发下输出一致（断言） |
| E12 | `action_records.steps` 同时含 V9 旧键与 V2.4.0 新键 | 新旧键共存时读取路径正确（新键优先、旧键兜底） |
