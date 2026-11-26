# V2.4.0 Tool System Tasks

> **上游**：`docs/version/v2.4.0/tool-system/architecture.md`
> **状态**：任务拆分稿（仅拆分，未排期、未实现）
> **主干**：按推荐拆分 TOOL-001 ~ TOOL-010 排列（依赖顺序即文档顺序）
> **增补**：TOOL-011 / TOOL-012（承载 Architecture 中无对应主干的交付面，见 §6 追溯矩阵）
> **说明**：本文档只做任务级拆分，不展开 Task Detail、不含代码。

---

## 1. 任务总览

| ID | Task Name | Priority | Dependencies | Phase |
|---|---|---|---|---|
| TOOL-001 | Tool Core Model | P0 | — | Phase 1 核心地基 |
| TOOL-002 | Tool Registry | P0 | TOOL-001 | Phase 1 核心地基 |
| TOOL-003 | Tool Executor | P0 | TOOL-002 | Phase 1 核心地基 |
| TOOL-004 | Tool Calling Pipeline | P0 | TOOL-002, TOOL-003 | Phase 2 治理与调用链 |
| TOOL-005 | Tool Permission System | P0 | TOOL-003, TOOL-004 | Phase 2 治理与调用链 |
| TOOL-006 | Autonomy Integration | P1 | TOOL-004, TOOL-005 | Phase 3 系统集成 |
| TOOL-007 | World Simulation Integration | P1 | TOOL-004, TOOL-005 | Phase 3 系统集成 |
| TOOL-008 | Memory Integration | P1 | TOOL-003, TOOL-005 | Phase 3 系统集成 |
| TOOL-009 | Reflection Integration | P2 | TOOL-003 | Phase 3 系统集成 |
| TOOL-010 | Built-in Tools | P1 | TOOL-002, TOOL-003, TOOL-005, TOOL-007 | Phase 4 能力落地与验收 |
| TOOL-011 | 外部能力接入（增补） | P2 | TOOL-005, TOOL-010 | Phase 4 能力落地与验收 |
| TOOL-012 | 系统验收与回归清单（增补） | P0 | TOOL-001 ~ TOOL-011 | Phase 4 能力落地与验收 |

**Priority 语义**：P0 = 版本发布阻断项（缺一不可上线）；P1 = 版本价值主体；P2 = 可延后至版本内末尾或下一版本。
**Priority ≠ 顺序**：TOOL-012 为 P0 但必须最后执行（验收性质决定）。

### 阶段划分

| Phase | 任务 | 阶段目标 |
|---|---|---|
| **Phase 1 核心地基** | 001, 002, 003 | 类型契约、声明权威、执行纪律三者就位；可独立灰度验证 |
| **Phase 2 治理与调用链** | 004, 005 | 工具被"选出来"且"管得住"；调用链与授权闸贯通 |
| **Phase 3 系统集成** | 006, 007, 008, 009 | 与 Autonomy / World / Memory / Reflection 四系统接线完成 |
| **Phase 4 能力落地与验收** | 010, 011, 012 | 工具供给落地、扩展通道打通、版本级验收 |

---

## 2. 依赖关系

### 2.1 依赖图

```text
TOOL-001 Tool Core Model
    │
    ▼
TOOL-002 Tool Registry
    │
    ▼
TOOL-003 Tool Executor ──────────────┬──────────────────┐
    │                                │                  │
    ▼                                │                  │
TOOL-004 Tool Calling Pipeline       │                  │
    │                                │                  │
    ▼                                │                  │
TOOL-005 Tool Permission System      │                  │
    │                                │                  │
    ├──────────────┬─────────────┬───┴──────────┐       │
    ▼              ▼             ▼              ▼       │
TOOL-006       TOOL-007      TOOL-008      TOOL-009 ◄──┘
Autonomy       World Sim      Memory        Reflection
    │              │             │              │
    │              ▼             │              │
    │         TOOL-010 Built-in Tools ◄─────────┘
    │              │
    │              ▼
    │         TOOL-011 外部能力接入
    │              │
    └──────────────┴──────────────► TOOL-012 系统验收与回归
```

### 2.2 关键路径

```text
TOOL-001 → TOOL-002 → TOOL-003 → TOOL-004 → TOOL-005 → TOOL-007 → TOOL-010 → TOOL-011 → TOOL-012
```

（9 个任务，为本版本最长依赖链；TOOL-006 / 008 / 009 不在关键路径上，可与 TOOL-007 并行。）

### 2.3 并行建议

| 可并行组 | 任务 | 前提 |
|---|---|---|
| A | TOOL-006 ‖ TOOL-007 ‖ TOOL-008 ‖ TOOL-009 | TOOL-005 完成 |
| B | TOOL-009 ‖ TOOL-010 | TOOL-003 完成即可启动 009 |
| C | TOOL-004 与 TOOL-003 部分工作重叠 | TOOL-002 完成（surface 投影可先于执行器做纯函数开发） |

---

## 3. 任务明细

### TOOL-001 Tool Core Model

- **Task ID**：TOOL-001
- **Task Name**：Tool Core Model
- **Priority**：P0
- **Goal**：建立工具域的**唯一类型契约与配置骨架**，为后续全部任务提供不可变的值对象与纯函数，不含任何 IO、执行与治理逻辑。交付工具域值对象全集（`ToolDefinition` / `ToolParameter` / `ToolSchema` / `PermissionProfile` / `ToolBinding` / `ToolInvocation` / `ToolExecution` / `ToolResult` / `ToolEffect` / `ToolObservation` / `ToolSurface` / `ToolHealth`）与两个纯函数（`ToolLifecycle` 四态状态机、权限等级排序与下限判定）；交付 `v24_*` Flag 与参数配置域，并把 v24 串行链校验并入既有 enablement 启动校验；扩展行动域 `GATE_REASONS` 值域以承载工具视角的细粒度未执行原因。
- **Dependencies**：无
- **Acceptance Criteria**：
  - 全部值对象可实例化，并通过 `model_dump` / `model_validate` 序列化往返测试；`ToolLifecycle` 迁移表与权限等级排序为纯函数且覆盖全枚举（含非法迁移返回 None）。
  - `v24_tool_system_enabled` 总闸与全部子闸默认 off；任一子闸开启而总闸关闭时启动 fail-fast，且违规原因中文可读。
  - `GATE_REASONS` 新增 `permission_denied` / `invalid_params` / `pending_confirmation` 三值，既有枚举测试零失败（值域扩展、无结构变更）。
  - 静态断言：模型层零 `app.repositories` / `app.application` / `app.services` 依赖（纯值对象纪律，同 `models/action.py`）。
  - Flag 全 off 时全量既有测试零修改通过。

---

### TOOL-002 Tool Registry

- **Task ID**：TOOL-002
- **Task Name**：Tool Registry
- **Priority**：P0
- **Goal**：交付工具的**声明与发现唯一权威**。实现模块级单例注册表（`register` / `unregister` / `resolve` / `get` / `has` / `list` / `namespaces` / `describe` / `health` / `record_outcome`），建立五个命名空间（`builtin` / `channel` / `world` / `ext.api` / `user`）与四态生命周期（enabled / disabled / deprecated / removed）；把 V9 既有六个 Capability 声明为工具定义（**只声明，不实现新能力**）；落地注册期七项校验（id 格式 / id 唯一 / 命名空间白名单 / capability 可解析 / schema 与 ActionSchema 自洽 / permission 合法 / 描述字段长度预算）。工具定义的权威来源是**代码**，运行期禁用清单走 settings，健康度为内存态——**不新建任何表**。
- **Dependencies**：TOOL-001
- **Acceptance Criteria**：
  - 工具集快照测试稳定：同一代码版本 `describe()` 输出逐字节可复现。
  - 七项注册校验各有负例测试，失败即抛错且错误信息可读（含冲突项与原因）。
  - 命名空间默认最低等级生效且**只升不降**：未声明 override reason 的降级请求被拒绝。
  - 生命周期：`disabled` / `deprecated` 工具不出现在新工具面；`deprecated` 的存量引用仍可执行；状态判定可回答"谁注册 / 何时启用 / 当前状态 / 最近健康度"四问。
  - `health()` 只读、`record_outcome()` 为唯一写入面且仅写内存态；重启归零（不持久化断言）。
  - 注册表惰性构建且单例（与既有 Capability 注册表同构）；总闸 off 时不被构建。

---

### TOOL-003 Tool Executor

- **Task ID**：TOOL-003
- **Task Name**：Tool Executor
- **Priority**：P0
- **Goal**：交付**执行纪律层**——固定短路顺序（resolve → 权限 → 校验 → 调用 → 归一）的执行器，复用 V9 既有能力执行器的超时包裹、异常归一与 usage 计时，**不复制其代码**；新增双层参数校验（结构校验 + 领域语义校验器注册表）与 `CapabilityResult → ToolResult` 结构化归一（effects / observations / failure_kind / usage / redacted）；把执行结果落 `action_records.steps` 既有台账（含 tool_id / permission / validation 新增字段）。同任务交付工具健康度与熔断（连续失败达阈值自动禁用、冷却后半开、熔断期从工具面剔除）。权限段在本任务以"总闸关闭时 allow-all"的占位形态存在，由 TOOL-005 替换为真实判定。
- **Dependencies**：TOOL-002
- **Acceptance Criteria**：
  - 五段短路顺序有专项测试；任一前置段失败路径**零外部调用**（打桩断言，含 DB 写与网络）。
  - 参数校验在执行前拦下，产出字段级可读理由；`normalized` 参数消除时间、空白、枚举的等价形式分歧；未声明字段被拒（严格模式）。
  - `CapabilityResult → ToolResult` 全量映射测试通过，且 V9 旧读键（`world_event_id` / `memory_id` / `failure_kind` / `deferred_world_op`）保留双写，兼容窗口 ≥ 一个版本。
  - 超时与异常归一行为与 V9 既有执行器逐字节一致（回归对照测试）。
  - 熔断：连续失败达阈值自动禁用、冷却后半开、重启归零；熔断期间该工具不出现在任何工具面。
  - `action_records.steps[]` 落库形状快照测试通过；Flag off 时 `steps[].result` 为 V9 原始结果形态（逐字节一致）。
  - 台账落库不新增表、不新增迁移。

---

### TOOL-004 Tool Calling Pipeline

- **Task ID**：TOOL-004
- **Task Name**：Tool Calling Pipeline
- **Priority**：P0
- **Goal**：交付"从用户消息到工具结果"的**完整调用链**。实现工具面投影与选择（工具面解析器 / 选择器 / 投影策略，纯函数、零 IO 零 LLM），按 Run Profile、日时段、场景、关系阶段、世界可用性、工具状态六个维度投影可用工具面并记录裁剪原因；把工具面接入既有决策管线的 capability 候选（工具 id 参与六维评分与四闸）；计划装配在总闸开启时经注册表解析绑定；前台后处理第 9 步**内部增强（不新增步骤）**；并交付管理面调试端点（工具清单 / 单工具详情 / 工具面投影含裁剪原因 / 执行台账投影）。
- **Dependencies**：TOOL-002, TOOL-003
- **Acceptance Criteria**：
  - 同一意图在不同 Run Profile、日时段、关系阶段下投影出**不同工具面**，且 `surface_hash` 同输入同输出（可复现锚点）。
  - 工具面裁剪可解释：每条 excluded 携带 reason；工具面上限参数生效且超限按 priority 截断。
  - 选择器在一词多工具时按 priority + tool_id 字典序确定性 tiebreak（重复运行结果完全一致）。
  - 工具候选进入六维评分并落决策审计；前台"回复恒优先"铁律不被破坏（chat_response 候选仍恒胜出）。
  - 前台管线与后处理的步骤序列、阶段数与 V2.3.0 一致（形状快照对照）。
  - 调试端点全部受总闸门控，Flag off 时端点不可见；执行台账由 `action_records.steps` 正确投影。

---

### TOOL-005 Tool Permission System

- **Task ID**：TOOL-005
- **Task Name**：Tool Permission System
- **Priority**：P0
- **Goal**：交付**执行前的授权闸**与确认流。实现四档权限等级（safe / normal / sensitive / dangerous）判定、命名空间默认等级下限、四类授权粒度（会话 / 工具 / 范围 / 通道）、默认拒绝（fail-closed）的七步短路判定；交付确认流服务（确认请求复用既有待办触发台账，**不新建表**）、授权复用（首次确认后落授权 + TTL）与授权撤销；补齐敏感字段脱敏与高风险操作强制审计。授权闸与 V9 既有六闸门**正交串联**（六闸门判"能不能执行"，权限闸判"该不该执行"），任一闸门不得被绕过。
- **Dependencies**：TOOL-003, TOOL-004
- **Acceptance Criteria**：
  - 四档等级判定表逐条测试；任何未明确 allow 的情况一律 deny（含范围越界、不受信命名空间、无授权）。
  - `confirm_required` 路径**零外部调用**（打桩断言），并生成角色语气的确认话术（非系统公告口吻，长度在预算内）。
  - 确认请求落既有待办触发台账且 TTL 到期自动清理；用户批准后作为新一轮触发执行，**参数与幂等键复用原调用**（不重新抽取、不重复发送）。
  - 等级只升不降：命名空间默认等级为下限，降级需显式 override reason 且评审单列。
  - 敏感参数进台账前脱敏，且脱敏字段名记入 `redacted`；高风险等级工具审计开关恒为 True。
  - 安全不变量十条各有对应断言，含"不存在可修改权限的工具"与外部返回内容的不可信标记。
  - 不新增表、不新增迁移（确认请求的字段复用若需扩列，须在任务内裁决并记录）。

---

### TOOL-006 Autonomy Integration

- **Task ID**：TOOL-006
- **Task Name**：Autonomy Integration
- **Priority**：P1
- **Goal**：让 Autonomy 2.0 **真正感知并调用工具**。首次把工具面实传给既有决策管线的 capability 候选参数（关闭"参数存在但从未传入"的既有断层）；策略快照新增有界工具事实段（可用工具 / 最近失败 / 已熔断），由既有行动事实收集同源扩展；自治工具面按 Run Profile 收窄（不含通道类工具，避免无人在线时主动外发）；钉死 **Action = Intent，Tool = Execution** 的编排关系——自治只产出意图，执行经既有行动编排器与工具执行器，额度、冷却、预算数学一律不变。
- **Dependencies**：TOOL-004, TOOL-005
- **Acceptance Criteria**：
  - 自治 tick 传入的工具面正确且不含通道类工具；Flag off 时仍传空值（与 V2.3.0 逐字节一致）。
  - 工具事实段有界（受可观测预算约束），装配失败降级为空包且不阻塞 tick。
  - 既有自治产行动日额度与活跃配额**未放宽**；自治产行动分支形态不变。
  - 端到端链路通过：Autonomous Decision → Create Action → Execute Tool → Receive Result → Update World State（经 outbox），且 Run 台账 / 决策记录 / 行动记录三账对齐可追溯。
  - 行为差异只在 Flag on 时出现（off 态行为快照对照零差异）。

---

### TOOL-007 World Simulation Integration

- **Task ID**：TOOL-007
- **Task Name**：World Simulation Integration
- **Priority**：P1
- **Goal**：钉死工具与世界的**读写契约**。交付工具上下文的世界事实预读装配（当前世界 / 库存 / 用户处境 / 场景 / 关系），沿用既有闸门快照的"调用方预读、闸门内零 IO"范式；工具写世界一律经延迟投递唯一路径（产出世界操作 → outbox → 消费器 → 世界引擎），**工具永不直接修改世界状态**；交付"工具实现体禁止直写世界域与角色域"的静态扫描护栏；预留角色意图提交接口（把"角色想做什么"交给世界侧裁决，本版本只冻结接口不实现）；工具面投影消费 V2.3.0 的日时段、场景画像与用户处境。
- **Dependencies**：TOOL-004, TOOL-005
- **Acceptance Criteria**：
  - 静态扫描断言：工具服务目录与各工具实现体内零世界仓储、零角色状态、零关系域导入。
  - 工具写世界全部经延迟投递，且消费幂等与崩溃重放续走行为与 V9 一致。
  - 工具上下文预读失败逐段降级（不抛错、不阻塞工具调用）；工具实现体内零仓储读取。
  - 世界事实可进工具参数与语义校验（地点存在性、物品在库两项端到端通过）。
  - 角色意图提交接口形状冻结并有 schema 测试（实现留待后续版本，明确标注为未接线）。
  - V2.3.0 世界侧测试零失败（世界唯一写面与事件唯一事实源未被触碰）。

---

### TOOL-008 Memory Integration

- **Task ID**：TOOL-008
- **Task Name**：Memory Integration
- **Priority**：P1
- **Goal**：交付工具结果的**记忆分层**。把行动记忆边界表泛化到工具维度（键从行动类型升级为工具的记忆策略键，旧键保留兼容），落地三条硬纪律：读类工具强制不沉淀、外部 API 结果默认不沉淀、自定义命名空间默认不沉淀；重要结果经既有记忆政策校验后落库（**零豁免**）；泛化记忆桥的内容模板与 effects 幂等标记（不重复投递）；失败结果以"上次没能帮用户完成"语义沉淀且重要度提升。
- **Dependencies**：TOOL-003, TOOL-005
- **Acceptance Criteria**：
  - 普通结果**不落记忆表**（零写入断言）；重要结果进候选并经既有政策校验后落库。
  - 读类工具即使配置为沉淀也被强制不沉淀（配置不可违背）。
  - 外部 API 与自定义命名空间结果默认不沉淀，需显式声明且总闸开启。
  - 幂等：同一次执行重复投递不产生第二条记忆。
  - 失败结果沉淀形态正确（重要度 ≥ 0.6、类型为重要事件、内容带未完成语义）。
  - 记忆表结构零变更、零迁移；Flag off 时记忆桥走 V9 原路径。

---

### TOOL-009 Reflection Integration

- **Task ID**：TOOL-009
- **Task Name**：Reflection Integration
- **Priority**：P2
- **Goal**：让反思**分析工具效能**。在既有证据窗聚合器上扩三个证据窗（工具使用效果 / Action 成功率 / 用户反馈），复用既有 reinforce 计数与三道闸；交付失败驱动的策略更新链（工具失败 → 证据聚合 → 三道闸 → Insight → 只读反哺决策与自治）；明确**反思不自动熔断工具**——反思管认知、健康度管运维，两条通道互不越界。
- **Dependencies**：TOOL-003
- **Acceptance Criteria**：
  - 三个证据窗各有场景用例；证据不足时不产 Insight（零 LLM 断言）。
  - 工具证据与用户证据走**完全相同**的三道闸（零豁免）；当日额度与幂等入队行为不变。
  - 隔离断言：反思产出的 Insight 不改变任何工具注册表状态（无自动熔断）。
  - 不产出"性格类"Insight（工具故障不改变人格）。
  - Flag off 时证据聚合行为与 V2.3.0 逐字节一致。

---

### TOOL-010 Built-in Tools

- **Task ID**：TOOL-010
- **Task Name**：Built-in Tools
- **Priority**：P1
- **Goal**：交付**工具供给与首批落地能力**。把 V9 六个既有能力的声明补全为可治理工具（提醒 / 记忆 / 世界动作 / 环境查询 / 检索 / 通知），并把两个既有空壳能力从"接口预留"推进到可用（检索至少接一个可用来源或明确降级语义与失败分类；通知落行动 note 与既有到期汇报）；交付通道类工具包装（复用既有出站契约、文本切分、幂等键与身份解析，**不新建通道**）作为高风险确认流样板；交付角色资产（工具语义描述文案、确认话术模板、工具面投影的场景与关系规则、记忆策略键）。
- **Dependencies**：TOOL-002, TOOL-003, TOOL-005, TOOL-007
- **Acceptance Criteria**：
  - ≥ 9 个内置工具可被描述、解析、执行，各自有端到端通过案例（成功 / 校验失败 / 权限拒绝三类路径齐全）。
  - 通道类工具首发需确认、确认后 TTL 内复用、文本切分不变式沿用既有测试、幂等键与出站契约对齐。
  - 检索与通知两个能力不再是"尚未接入"空壳（有可判定行为，或明确的降级语义与失败分类）。
  - 工具语义描述与确认话术在长度预算内（≤ 120 / ≤ 80 字）且经人工审核可读。
  - 新增一个内置工具的完整步骤 ≤ 4 步（有实操验证记录）。

---

### TOOL-011 外部能力接入（增补）

- **Task ID**：TOOL-011
- **Task Name**：外部能力接入
- **Priority**：P2
- **Goal**：打通**第三方能力扩展通道**。交付外部 API 工具的声明式注册（清单加载器、域名白名单、凭据仅从环境变量读取、响应字段映射），以及自定义命名空间工具的受限注册与校验（**无任意代码执行、无 HTTP 直连、无文件系统访问**——安全红线而非能力限制）。
- **Dependencies**：TOOL-005, TOOL-010
- **Acceptance Criteria**：
  - 新增一个外部 API 工具 ≤ 1 个声明文件；清单校验失败只告警不阻塞启动。
  - 域名白名单外一律拒绝；白名单为空时全禁；凭据缺失时工具为不可用（不抛错、不泄漏）。
  - 凭据零硬编码（静态扫描通过，示例环境变量文件补齐对应段落）。
  - 自定义命名空间工具默认高风险等级、默认不沉淀记忆、注册需显式授权；任意代码 / HTTP / 文件访问路径被拒（负例测试）。
  - 外部返回内容进观测时打不可信标记，不作为指令进入决策。

---

### TOOL-012 系统验收与回归清单（增补）

- **Task ID**：TOOL-012
- **Task Name**：系统验收与回归清单
- **Priority**：P0
- **Goal**：交付**版本级验收**。构建端到端场景集（六类工具 × 成功 / 校验失败 / 权限拒绝 / 确认流）、Flag 矩阵一致性测试、`docs/version/v2.4.0/tool-system/regression-checklist.md`，以及 Architecture §11.4 八个版本 Gate（G-COMPAT / G-GOVERN / G-SELECT / G-VALIDATE / G-PERMISSION / G-WORLD / G-MEMORY / G-EXTEND）的可执行判定。
- **Dependencies**：TOOL-001 ~ TOOL-011
- **Acceptance Criteria**：
  - Flag 全 off 时与 V2.3.0 逐字节一致（prompt + 行为快照 + 维护步骤序列）；既有测试零修改通过。
  - 八个版本 Gate 各有自动化或人工可判定条目，且全部可追溯到 Architecture §11.4。
  - 危险操作确认流端到端通过（含 TTL 过期路径与用户否定路径）。
  - 迁移与回滚：确认"零新建表"成立；若实现阶段出现建表需求，必须回退重审 Architecture §5.1 裁决并在验收记录中留痕。
  - 回归清单覆盖三禁令（不破坏 Agent / Memory / Session / Event 系统）与十条安全不变量。

---

## 4. 里程碑

| 里程碑 | 含任务 | 出口判定 |
|---|---|---|
| **M1 地基可用** | 001, 002, 003 | 工具可被声明、解析、执行、归一；Flag off 与 V2.3.0 逐字节一致 |
| **M2 治理闭环** | 004, 005 | 工具可被动态选出且授权闸贯通；危险操作需确认；默认拒绝生效 |
| **M3 四系统集成** | 006, 007, 008, 009 | Autonomy / World / Memory / Reflection 四系统接线完成且各自验收通过 |
| **M4 能力与验收** | 010, 011, 012 | 工具供给落地、扩展通道打通、八个 Gate 全绿 |

---

## 5. 遗留问题挂载

Architecture「附：遗留问题登记」中的八项按任务归属挂载，**在对应任务启动前需完成裁决**：

| # | 问题 | 挂载任务 | 裁决时点 |
|---|---|---|---|
| Q1 | 多步工具编排语义（并行 / 串行 / 部分失败回滚） | 不在本版本（`action_plan_max_steps` 保持 1） | 后续版本 |
| Q2 | 确认请求复用既有待办触发台账是否需扩列 | TOOL-005 | 任务内裁决（若需扩列则"零迁移"断言失效，须回写 Architecture） |
| Q3 | 自定义命名空间工具的 DSL 边界 | TOOL-011 | 任务启动前（先采用最保守形态） |
| Q4 | 工具面投影规则与 V2.3.0 场景画像 / 习惯触发器的资产形态收敛 | TOOL-004 | 任务内记录，统一协议留后续版本 |
| Q5 | 工具观测进回复素材的预算竞争 | TOOL-004 | 任务内记录，压测后决定 |
| Q6 | 外部 API 响应映射的表达式子集边界 | TOOL-011 | 任务内冻结 |
| Q7 | 工具健康度熔断与反思 Insight 的优先级 | TOOL-003 / TOOL-009 | 两任务联合裁决 |
| Q8 | 工具结果对关系域的信号映射是否扩展 | TOOL-010 | 任务内记录（涉及关系域写入面，需谨慎） |

---

## 6. 与 Architecture 的追溯矩阵

Architecture §11.2 定义了 14 项任务，本文档按推荐主干重组为 10 + 2 项，**交付面无遗漏**：

| Architecture 任务 | 本文档任务 | 说明 |
|---|---|---|
| TOOL-001 模型与设置骨架 | **TOOL-001** | 一一对应 |
| TOOL-002 ToolRegistry | **TOOL-002** | 一一对应 |
| TOOL-003 ParamValidator | **TOOL-003** | 并入执行器（校验是执行纪律的一环） |
| TOOL-004 PermissionGate + ConfirmationService | **TOOL-005** | 一一对应（编号调整） |
| TOOL-005 ToolExecutor + Normalizer | **TOOL-003** | 一一对应（编号调整） |
| TOOL-006 ToolDecision Layer | **TOOL-004** | 扩入调用链与管理面 |
| TOOL-007 Autonomy 集成 | **TOOL-006** | 一一对应 |
| —（Architecture §7.3 世界集成，原无独立任务） | **TOOL-007** | 本文档**新增独立任务**，把散落在 §7.3 的读写契约集中交付 |
| TOOL-008 Memory 集成 | **TOOL-008** | 一一对应 |
| TOOL-009 Reflection 集成 | **TOOL-009** | 一一对应 |
| TOOL-010 Channel Tool | **TOOL-010** | 与其余内置工具合并为"工具供给"任务 |
| TOOL-011 External API Tool | **TOOL-011** | 并入外部能力接入 |
| TOOL-012 调试端点与管理面 | **TOOL-004** | 并入调用链（观测面属于管线可见性） |
| TOOL-013 工具健康度与熔断 | **TOOL-003** | 并入执行器（熔断由执行结果驱动） |
| TOOL-014 验收测试与回归清单 | **TOOL-012** | 一一对应 |

**增补说明**：TOOL-011 与 TOOL-012 超出推荐拆分清单，原因是 Architecture 明确要求"支持未来扩展第三方能力"（G6）与版本级验收 Gate（§11.4），二者无法合理并入其余十个任务而不稀释其验收口径。若需严格收敛为 10 个任务，可将 TOOL-011 合并入 TOOL-010、TOOL-012 的验收条目分散至各任务的 Acceptance Criteria（但会失去统一的版本出口判定）。
