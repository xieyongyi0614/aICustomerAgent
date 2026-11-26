# TOOL-011 Task Detail — 外部能力接入

> 上游：[../architecture.md](../architecture.md) §10.2（外部 API 工具）、§10.3（用户自定义工具）、§9.5（安全不变量）、§7.8（Flag 设计）；[../tasks.md](../tasks.md) TOOL-011
> 状态：设计稿（未实现）
> 范围红线：**无任意代码执行**（安全红线，非能力限制）；凭据零硬编码（仅从环境变量读取）；域名白名单默认全禁；不新建表；不受信来源默认不沉淀记忆。

---

# 1. Task Overview

| 项 | 值 |
|---|---|
| **Task ID** | TOOL-011 |
| **Task Name** | 外部能力接入 |
| **Priority** | P2 |
| **Dependencies** | TOOL-005, TOOL-010 |
| **建议提交** | `feat: V2.4.0 外部能力声明式接入` |

## 1.1 Goal

打通**第三方能力扩展通道**，让"接入一个新外部能力"从改 Python 代码降为加一个声明文件，同时把安全边界固化为机制而非约定：

1. **外部 API 工具**：声明式注册（清单加载 / 域名白名单 / 凭据仅从环境变量 / 响应字段映射）。
2. **自定义工具**：受限 DSL 注册与校验（无任意代码、无 HTTP 直连、无文件系统访问）。

## 1.2 Scope

**包含**

- 新增 `app/services/tool/manifests/`：声明文件目录 + 加载器 + 清单校验。
- 新增 `app/services/tool/ext_api.py`：`ExternalApiCapability`（声明驱动的 HTTP 调用）。
- 新增 `app/services/tool/user_defined.py`：自定义工具的受限注册与校验。
- 新增 `app/services/tool/dsl.py`：受限 DSL 的动作白名单与组合校验。
- 扩展 `main.py` lifespan：清单加载（失败只告警不阻塞）。
- 扩展 `app/api/v1/debug.py`：外部工具与自定义工具的可见性。
- 单测：清单校验、白名单、凭据缺失、DSL 负例（越界路径全拒）。

**不包含（Non-Scope）**

- MCP / 工具协议对接（architecture §10.4 留后续版本）。
- 工具市场（审批面留后续）。
- 任意代码执行类扩展（**永久不做**）。
- 内置工具（TOOL-010）。

---

# 2. Technical Design

## 2.1 模块设计

| 文件 | 性质 | 职责 |
|---|---|---|
| `app/services/tool/manifests/` | 新增 | 声明文件目录（示例清单） |
| `app/services/tool/ext_api.py` | 新增 | 清单加载 + 校验 + `ExternalApiCapability` |
| `app/services/tool/dsl.py` | 新增 | 受限 DSL 动作白名单与组合校验 |
| `app/services/tool/user_defined.py` | 新增 | 自定义工具注册与校验 |
| `app/main.py` | 扩展 | lifespan 清单加载（告警不阻塞） |
| `app/api/v1/debug.py` | 扩展 | 外部/自定义工具可见性 + 清单加载状态 |

**两条接入路径**

```text
路径 A｜外部 API 工具（声明式，零 Python）
   manifests/*.yaml
        │ 启动时加载
        ▼
   清单校验（结构 / 白名单 / 凭据引用 / 映射表达式）
        │ 校验失败 → 只告警，跳过该条（不阻塞启动）
        ▼
   ToolDefinition 生成（namespace=ext.api，level=sensitive，confirm=first_time）
        │ 绑定
        ▼
   ExternalApiCapability（统一实现，声明驱动 HTTP）
        │ 执行时
        ▼
   host 白名单校验 → 凭据读取（环境变量）→ HTTP 调用 → 响应映射 → observations

路径 B｜自定义工具（受限 DSL）
   注册请求
        │
        ▼
   DSL 校验（动作白名单 / 组合合法性 / 无任意代码）
        │ 违规 → 拒绝注册（不留痕、不部分生效）
        ▼
   ToolDefinition 生成（namespace=user，level=dangerous，confirm=first_time）
        │ 绑定
        ▼
   组合既有 Capability / 内部动作（无任意代码执行）
```

## 2.2 数据结构

### 外部 API 清单结构（YAML）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `tool_id` | str | ✅ | 必须 `ext.api.` 前缀 |
| `name` | str | ✅ | ≤ 20 字 |
| `description` | str | ✅ | ≤ 120 字 |
| `capability` | str | ✅ | 固定 `external_api` |
| `action` | str | ✅ | 固定 `call` |
| `http.method` | str | ✅ | GET / POST（白名单） |
| `http.url` | str | ✅ | 必须 https |
| `http.auth` | dict | ⭕ | `{type: bearer/apikey/header, env: <VAR_NAME>}` |
| `http.params` | dict | ⭕ | 参数模板，`{params.<name>}` 占位 |
| `http.timeout_seconds` | float | ⭕ | 默认 5，上限 10 |
| `response_map` | dict | ✅ | 表达式 → observations 键 |
| `permission` | dict | ✅ | `{level, scope, confirm}`（level 不得低于 `sensitive`） |
| `side_effects` | list | ✅ | 不得含 `irreversible` |

### 清单校验规则（失败即跳过该条 + 告警）

| # | 校验 | 失败处理 |
|---|---|---|
| 1 | `tool_id` 前缀为 `ext.api.` 且符合格式 | 跳过 + 告警 |
| 2 | `http.url` 为 https 且 host 在 `v24_tool_ext_allowed_hosts` 内 | 跳过 + 告警 |
| 3 | `http.method` 在白名单内（GET / POST） | 跳过 + 告警 |
| 4 | `http.auth.env` 引用的环境变量存在 | 跳过 + 告警（**不在日志中打印变量值**） |
| 5 | `response_map` 表达式在支持的子集内 | 跳过 + 告警 |
| 6 | `permission.level >= sensitive` | 跳过 + 告警 |
| 7 | `side_effects` 不含 `irreversible` | 跳过 + 告警 |
| 8 | `description` / `name` 长度预算 | 跳过 + 告警 |

### 响应映射表达式子集（Q6 冻结）

| 支持 | 语法 | 示例 |
|---|---|---|
| 根路径 | `$.a.b.c` | `$.data.temp` |
| 数组索引 | `$.a[0].b` | `$.items[0].name` |
| 类型转换 | 后缀 `:str` / `:num` / `:bool` | `$.data.temp:num` |
| **不支持** | 函数 / 运算 / 条件 / 嵌套通配 | — |

超出子集的表达式在校验 5 阶段被拒。

### 自定义工具受限 DSL

| 能力 | 允许 | 禁止 |
|---|---|---|
| 组合既有 Capability 动作 | ✅（白名单内） | — |
| 参数映射与默认值 | ✅ | — |
| 条件分支 | ❌ | 复杂度与可审计性 |
| 循环 | ❌ | 同上 |
| HTTP 直连 | ❌ | **安全红线** |
| 文件系统访问 | ❌ | **安全红线** |
| 任意代码 / 表达式求值 | ❌ | **安全红线** |
| 读取记忆内容 | ❌（本版本） | 隐私面，Q3 待裁决 |

### 自定义工具声明结构

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool_id` | str | 必须 `user.` 前缀 |
| `name` / `description` | str | 长度预算同内置 |
| `steps` | list[dict] | `[{capability, action, params_map}]`，≤ 3 步 |
| `input_schema` | dict | 对外参数声明 |
| `side_effects` | list | 由步骤并集推导（不允许声明为只读但实际写） |

## 2.3 核心流程

### 清单加载（启动期，告警不阻塞）

```text
main.lifespan
   │  v24_tool_external_api_enabled off → 跳过
   ▼
加载 v24_tool_ext_manifest_path 下的 *.yaml
   ├─ 逐条解析 + 八项校验
   ├─ 通过 → 生成 ToolDefinition → registry.register
   ├─ 失败 → 记 warning（含文件名 + 失败项），**跳过该条**
   └─ 全部失败 → 注册表无 ext.api.* 工具（系统正常启动）
   ▼
加载结果落调试端点（loaded / skipped / reasons）
```

### 外部 API 执行（运行时二次校验）

```text
ExternalApiCapability.execute(action, params, ctx)
   ├─ ① host 白名单二次校验（防清单加载后配置变更）
   ├─ ② 凭据读取（环境变量；缺失 → unavailable，不抛错、不泄漏）
   ├─ ③ 参数模板渲染（{params.x} 占位替换）
   ├─ ④ HTTP 调用（timeout ≤ 10s；异常归一）
   ├─ ⑤ 响应映射（按 response_map 提取 → observations）
   └─ ⑥ 全部 observations 打 untrusted=True
```

**提示注入防线**：外部返回内容一律打 `untrusted=True` 标记，**只作事实素材，不作为指令进入决策**（§9.5 不变量 10）。

### 自定义工具注册

```text
register_user_tool(declaration)
   ├─ 总闸 + v24_tool_user_defined_enabled 双闸检查
   ├─ DSL 校验（§2.2 白名单 + 组合合法性 + 无任意代码）
   ├─ side_effects 由步骤并集推导（防止声明为只读而实际写）
   ├─ 强制 level=dangerous（不可降级）
   ├─ 记忆沉淀默认关闭（不可声明为沉淀）
   └─ 通过 → ToolDefinition → registry.register
       失败 → 拒绝（不留痕、不部分生效）
```

## 2.4 与已有系统交互

| 既有设施 | 交互方式 | 改动 |
|---|---|---|
| `services/tool/registry.py` | 清单加载与自定义注册经 `register` | 零改动 |
| `services/tool/executor.py` | 外部能力经统一执行器（超时/归一/权限） | 零改动 |
| `services/tool/permission.py` | `ext.api.*` / `user.*` 默认等级与不受信判定（TOOL-005 已实现） | 零改动 |
| `services/tool/validator.py` | 外部工具复用 `content_within_budget` 等校验器 | 零改动 |
| `services/tool/memory_policy.py` | 两命名空间默认不沉淀（TOOL-008 已实现硬纪律） | 零改动 |
| `services/action/registry.py::CapabilityRegistry` | 注册 `ExternalApiCapability` | 增量（注册一行） |
| `app/main.py` lifespan | 追加清单加载步骤（不新增常驻 task） | 增量 |
| `app/api/v1/debug.py` | 追加加载状态与工具可见性 | 增量 |
| `core/settings/tool.py` | 消费 `v24_tool_ext_manifest_path` / `v24_tool_ext_allowed_hosts` | 零改动（TOOL-001 已建） |
| HTTP 客户端 | 复用项目既有 HTTP 依赖（不引入新依赖） | 视项目现状 |

**与 V9 `NotificationCapability` 空壳的关系**：二者不同——`notification` 是内置能力的推进（TOOL-010），本任务的外部 API 是**声明驱动的通用 HTTP 能力**，不依赖具体业务能力实现。

---

# 3. Database Changes

**本任务无任何数据库变更。**

| 项 | 结论 | 说明 |
|---|---|---|
| Table | 无新增 | 工具定义权威来源是**声明文件 + 代码**，不落库（architecture §4.2.3 裁决） |
| Field | 无新增列 | 清单加载结果进内存态 + 调试端点 |
| Index | 无新增 | — |
| Migration | **无** | — |

**反模式警示（评审红线）**：

- 不得为"自定义工具注册"建表——注册是**运行期内存态**，重启后由声明文件 / 注册请求重建。
- 不得把凭据写入任何持久化结构（DB / 声明文件 / 日志）——**只从环境变量读取**。

---

# 4. API / Interface Design

## 4.1 清单加载接口

```text
interface ToolManifestLoader:
    load(path: str) -> LoadReport

LoadReport:
    loaded: list[str]          # 成功注册的 tool_id
    skipped: list[dict]        # {file, tool_id?, rule, reason}
    total: int
```

| 项 | 内容 |
|---|---|
| **Input** | 清单目录路径（来自 settings） |
| **Output** | `LoadReport` |
| **失败形态** | **不抛异常**——逐条跳过并汇总；目录不存在返回空报告 |
| **纪律** | 启动期调用；不阻塞启动；不在日志打印凭据值 |

## 4.2 外部 API 能力接口

```text
interface ExternalApiCapability:
    name: str = "external_api"
    actions: {"call": ActionSchema}

    validate(action: str, params: dict) -> list[str]

    async execute(action: str,
                  params: dict,
                  ctx: ExecutionContext) -> CapabilityResult
```

| 项 | 内容 |
|---|---|
| **Input** | 声明驱动的参数（由 `input_schema` 校验后传入） |
| **Output** | `CapabilityResult`（`payload.observations` 全部 `untrusted=True`） |
| **失败形态** | 凭据缺失 → `unavailable`；网络异常 → `transient`；HTTP 4xx → `permanent`；5xx → `transient`；超时 → `timeout` |

## 4.3 自定义工具注册接口

```text
interface UserToolRegistrar:
    validate(declaration: dict) -> ValidationReport
    register(declaration: dict) -> str            # 返回 tool_id
    unregister(tool_id: str) -> None
    list_registered() -> list[str]
```

| 项 | 内容 |
|---|---|
| **Input** | 自定义工具声明 |
| **Output** | `tool_id` 或 `ValidationReport` 错误 |
| **失败形态** | 任一校验失败 → 拒绝（不留痕、不部分生效） |
| **纪律** | 强制 `level=dangerous`；强制不沉淀记忆；`side_effects` 由步骤并集推导 |

## 4.4 受限 DSL 接口

```text
interface ToolDSL:
    allowed_actions() -> frozenset[tuple[str, str]]     # (capability, action) 白名单
    validate_steps(steps: list[dict]) -> list[str]      # 返回错误列表
    derive_side_effects(steps: list[dict]) -> tuple[str, ...]
```

## 4.5 调试端点（增量）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/debug/tools/manifests` | 清单加载报告（loaded / skipped / reasons） |
| GET | `/api/v1/debug/tools/external` | 外部 API 工具清单（不含凭据值） |
| GET | `/api/v1/debug/tools/user-defined` | 自定义工具清单 |
| POST | `/api/v1/debug/tools/user-defined/{tool_id}/revoke` | 注销自定义工具 |

---

# 5. Implementation Plan

## Step 1 — 清单加载与校验

1. 定义清单结构（§2.2）与八项校验（每项独立可测）。
2. 实现 `ToolManifestLoader.load`：逐条解析、校验、注册、汇总报告。
3. 接入 `main.lifespan`（总闸门控；失败只告警）。
4. 单测：八项校验各一负例；目录不存在；全失败仍正常启动；日志不含凭据值（断言）。

## Step 2 — 外部 API 能力

1. 实现 `ExternalApiCapability`：白名单二次校验 → 凭据读取 → 参数渲染 → HTTP → 响应映射。
2. 实现响应映射表达式子集解析（`$.a.b[0].c` + `:str/:num/:bool`），超子集拒绝。
3. 全部 observations 打 `untrusted=True`。
4. 单测：错误分类映射；凭据缺失返回 unavailable；host 白名单外拒绝；映射子集正负例；零硬编码扫描。

## Step 3 — 自定义工具与调试面

1. 实现 `ToolDSL`：动作白名单 + 步骤校验 + `side_effects` 推导。
2. 实现 `UserToolRegistrar`：校验 → 强制 dangerous → 强制不沉淀 → 注册。
3. 调试端点四项。
4. 单测：DSL 负例全拒（HTTP 直连 / 文件访问 / 任意代码 / 超 3 步 / 只读声明但写实际）；注册拒绝不留痕；端点门控。
5. 回归：Flag 全 off 时清单不加载、自定义注册不可用；既有测试零修改通过。

---

# 6. Acceptance Criteria

## 6.1 Functional Acceptance

- 新增一个外部 API 工具 **≤ 1 个 YAML 声明文件**（无 Python 改动）。
- 清单八项校验各有负例测试；校验失败只告警、跳过该条，**不阻塞启动**。
- 域名白名单：白名单外一律拒绝；`v24_tool_ext_allowed_hosts` 为空时**全禁**。
- 凭据缺失 → 工具 `unavailable`（不抛错、不泄漏值）；日志与调试端点中凭据值不可见（断言）。
- 响应映射子集正例通过、超子集（函数 / 运算 / 条件）被拒。
- 外部返回内容全部打 `untrusted=True`；不作为指令进入决策。
- 自定义工具：注册需双闸；强制 `level=dangerous`；强制不沉淀记忆；`side_effects` 由步骤并集推导。
- DSL 负例全拒：HTTP 直连 / 文件系统访问 / 任意代码 / 超 3 步 / 只读声明但实际写。

## 6.2 Integration Acceptance

- 凭据**零硬编码**（静态扫描通过）；`.env.example` 补齐对应段落（占位，不含真实值）。
- 外部工具与自定义工具经**统一执行器**（权限 / 校验 / 超时 / 归一全部生效，无旁路）。
- `ext.api.*` / `user.*` 的记忆沉淀硬纪律生效（配置声明沉淀仍不沉淀）。
- `main.py` 不新增常驻 task（仅 lifespan 追加加载步骤；diff 断言）。
- 声明文件目录与加载器不引入新第三方依赖（依赖 diff 断言）。
- **Flag 全 off 时**：清单不加载、自定义注册拒绝、`ext.api.*` 工具不存在；既有测试零修改通过。

## 6.3 Edge Cases

| # | 场景 | 期望 |
|---|---|---|
| E1 | `v24_tool_ext_manifest_path` 为空 | 不加载任何清单；报告为空；正常启动 |
| E2 | 目录存在但无 `.yaml` 文件 | 报告 `total=0`；正常启动 |
| E3 | 清单 YAML 语法错误 | 跳过该文件 + 告警（含文件名与语法错误位置）；其他文件继续加载 |
| E4 | `http.auth.env` 引用的环境变量不存在 | 跳过该条 + 告警（**不打印变量名以外的信息**） |
| E5 | 运行期白名单配置被改窄（清单已加载） | 执行时二次校验拒绝 → `denied`，不发起请求 |
| E6 | HTTP 响应结构不符合 `response_map` | observations 对应键缺省（不抛错）；`status=succeeded`（请求本身成功） |
| E7 | HTTP 超时 | `failure_kind=timeout`，既有退避重试 |
| E8 | HTTP 返回 4xx | `failure_kind=permanent`，不重试 |
| E9 | HTTP 返回内容含指令性文本（提示注入） | 打 `untrusted=True`；不作为指令；仅作事实素材 |
| E10 | 自定义工具声明含 HTTP 直连步骤 | DSL 校验拒绝；不注册、不留痕 |
| E11 | 自定义工具声明为只读但步骤含写动作 | `side_effects` 推导覆盖声明 → 按写类处理（或拒绝，取更保守者） |
| E12 | 自定义工具引用不存在的 capability | 校验拒绝 |
| E13 | 自定义工具注册后重启进程 | 注册丢失（内存态）；需重新注册（明确语义，非缺陷） |
| E14 | 注销自定义工具后再次调用 | `unavailable`（未注册）；不抛错 |
| E15 | 同一 `tool_id` 在多个清单文件中重复 | 首条注册成功，后续跳过 + 告警（不覆盖） |
| E16 | 清单声明 `side_effects` 含 `irreversible` | 校验 7 拒绝 |
| E17 | 调试端点查询外部工具 | 返回声明信息，**不含凭据值**（断言响应体无 secret 模式串） |
