# FEISHU-006 — 错误处理与测试收口

> 上游：[../tasks.md](../tasks.md) FEISHU-006 ｜ 架构：[../architecture.md](../architecture.md) §6（全节）/ §2.2 / §7.2 ｜ 依赖：**FEISHU-002、003、004、005**
> Priority：**P1** ｜ 层级：Closure（P0 链的验收证据来源；本 Task 不新增业务能力）
> **本 Task 的产出形态**：`第 6.1 节十五类错误逐条可断言` + `依赖边界守门（R1~R5）` + `未启用零路径证明` + `Proactive 出口能力验证` + `人工冒烟清单`。**不含**任何新功能。

---

## 1. Goal

前四个 Task 各自证明了"我的路径是正确的"；本 Task 证明**"它们拼在一起仍然正确，且没有越界"**：

```text
① 错误矩阵收口    第 6.2 节 15 类错误 → 逐条可执行断言（触发条件/HTTP/是否调管线/用户可见/是否重试）
② 场景矩阵全绿    正常·空·超长·重复·群聊·非文本·加密·验签·解密·管线异常 · 隔离 · ★Proactive 出站
③ 依赖边界守门    （本次修订按 R1~R5 重构）
                  R1/R2 核心可 import channels.base（契约）但不得 import channels.<impl>
                  R3    channels.<impl> 不得 import 任何 Autonomy / Life Loop / Scheduler / Policy
                  R4    channels/base.py 零第三方依赖、零 app.* 依赖
④ 零路径证明      FEISHU_ENABLED=false → 网络调用 / token 获取 / 管线调用 / DB 写 计数全部为 0
⑤ Proactive 出口   已知 internal_user_id → 解析到 external_id → 发送成功（不实现 Autonomy）
⑥ 人工冒烟清单    真实模型 + 真实飞书应用的回调演练（含真模型抽查项）
```

**本 Task 的价值不在代码量，而在于把"架构承诺"变成"可执行的守门断言"。** 前四个 Task 的 Acceptance 都是"我做到了"；本 Task 的 Acceptance 是"**别人以后改坏了会被立刻发现**"。其中 ③ 是**唯一**能证明"飞书没有侵入核心、核心也没有绑死飞书"的手段。

## 2. Dependencies

| 依赖 | 提供物 | 使用方式 |
|---|---|---|
| **FEISHU-002** | 入站端点、事件校验/解析/去重纯函数、后台派发 | 端到端与边界用例的被测对象 |
| **FEISHU-003** | 身份映射、`channel_identities`、隔离不变式 | 隔离回归的被测对象 |
| **FEISHU-004** | `TurnOutcome`、串行/队列、错误语义映射 | 管线/隔离用例的被测对象 |
| **FEISHU-005** | 出站投递、切分、出站重试幂等 | 出站失败矩阵的被测对象 |
| 既有 | `tests/conftest.py`（FakeLLM / 内存 SQLite / `wait_until` / `spawn_background` 等待） | 测试基建 |
| 既有 | `docs/TESTING.md` | 测试分层、marker、执行级别规范 |

> **本 Task 是唯一允许"回头补齐/加固前序 Task 测试"的 Task**，但**不得借机修改前序 Task 的实现逻辑**（除修复被测试暴露的缺陷）。

## 3. Scope

**做**：

1. **错误矩阵收口**：把架构 §6.2 的 15 类错误（含本次新增的 #14 #15）逐条落为断言（见 §6.1 的完整矩阵与 §12 的落点）。
2. **静态依赖边界断言**（双向）——**常驻**测试（§6.4）。
3. **未启用零路径**断言（网络 / token / 管线 / DB 四类计数）。
4. **多用户隔离回归**（会话 / 记忆 / 世界 / 库存 / 关系 / 角色状态六项 + 并发场景）。
5. **人工冒烟清单**：`docs/integrations/feishu/regression-checklist.md`（**实现本 Task 时创建**，本次 Detail 生成不创建，§15.4）。
6. **排障可见性**（可选、最小）：复用既有 observability trace，或在 `api/v1/debug.py` 增只读查询（§6.7）。
7. 前序 Task 测试的**空缺补齐**（不重复已覆盖项）。

**不做**（见 §14）：任何新功能、群聊、Streaming、卡片、主动消息、图片/文件/语音、账号绑定、真实飞书调用、真实 LLM 调用。

## 4. Files

### New Files

```text
tests/unit/test_feishu_error_matrix.py         # §6.1 十五类错误的分类与响应语义
tests/unit/test_feishu_boundary.py             # ★ 静态依赖边界（AST 扫描；方向一/二/三）
tests/integration/test_feishu_cases.py         # 场景矩阵（内存 SQLite + FakeLLM + 假传输）
tests/integration/test_feishu_isolation.py     # ★ 多用户隔离回归（六项资源 + 并发）
tests/integration/test_feishu_proactive.py     # ★ Proactive 出口能力端到端收口（本次修订新增）
tests/e2e/test_feishu_disabled.py              # ★ 未启用零路径（四类计数）
docs/integrations/feishu/regression-checklist.md   # 人工冒烟清单（实现本 Task 时创建）
```

> `test_feishu_proactive.py` 与 FEISHU-005 的 `test_feishu_proactive_flow.py` 分工：后者测**投递层**（解析→send 的单元/集成行为），前者测**跨 Task 收口**（003 建身份 → 005 投递 → 隔离断言 → 无 Autonomy 参与）。

### Modified Files

```text
tests/conftest.py                  # ① 若 002/004 自建任务集合则并联等待；② 慢测试登记 SLOW_TEST_FILES
api/v1/debug.py                    # 仅当采用 §6.7 的最小排障端点（可选；不采用则不动）
docs/integrations/feishu/tasks.md   # 可选：把白名单扩展（core/db.py）与偏差（拒绝最新）回填（§15.3）
```

### Forbidden Files（**本 Task 的特殊红线**）

```text
app/channels/**                    # ★ 除"修复被测试暴露的缺陷"外，不得改动实现
app/application/**                 # ★ 零改动（AC 硬闸）
app/services/**（既有域服务）        # ★ 零改动
app/repositories/**                # ★ 零改动
app/character/**  app/chains/**  app/models/**
api/v1/chat.py  api/v1/schemas.py
migrations/**
architecture.md                    # ★ 不得修改（本次生成范围内亦不得）
task-details/FEISHU-001.md          # ★ 不得修改
```

> **红线说明**：006 若顺手"优化"了 002~005 的实现，就等于让"验收者"变成"被验收者"，收口证据失去独立性。改动只允许发生在**测试文件**与**文档**。

## 5. Architecture / Data Flow

### 5.1 测试分层映射（对齐 `docs/TESTING.md`）

```text
                 ┌──────────────────────────────────────────────┐
   unit          │  纯函数：事件校验/解析/解密/切分/派生/分类     │  零 IO，最快
                 │  + ★ AST 静态边界扫描（不 import 被测模块）    │
                 └──────────────────────────────────────────────┘
                 ┌──────────────────────────────────────────────┐
   integration   │  走真实编排：入站→身份→管线→出站（FakeLLM +   │  内存 SQLite
                 │  假传输）；隔离矩阵；并发/串行/队列；落库断言  │
                 └──────────────────────────────────────────────┘
                 ┌──────────────────────────────────────────────┐
   e2e / api     │  端点级：ASGITransport → 状态码/时序/零路径    │  含 disabled 404
                 └──────────────────────────────────────────────┘
                 ┌──────────────────────────────────────────────┐
   人工冒烟       │  真实模型 + 真实飞书应用（regression-checklist）│  真人执行
                 └──────────────────────────────────────────────┘
```

### 5.2 三层证据的对应关系

| 证据层 | 证明什么 | 谁需要它 |
|---|---|---|
| 自动化矩阵 | "代码在受控输入下行为正确" | 开发者 / 未来 AI 改代码时 |
| 静态边界断言 | "**结构上**不可能越过架构边界"（不依赖人的自觉） | 架构约束本身 |
| 人工冒烟 | "真实飞书协议 + 真实模型下端到端可用" | 上线前 |

**三者不可互相替代**：自动化测试无法证明"真实飞书协议对不对"（契约由官方文档保证）；静态断言无法证明"逻辑对不对"；人工冒烟无法防回归。

## 6. Detailed Implementation

### 6.1 错误矩阵（完整版，15 类 + 承接）

> 来源：architecture.md §6.2。本表是**验收清单**：每条都必须有对应的可执行断言。

| # | 场景 | 触发方式（测试） | HTTP | 调管线 | 用户可见 | 重试 | 归属 |
|---|---|---|---|---|---|---|---|
| 1 | Webhook 验证失败（token） | 伪造 `header.token` | `401` | ❌ | 无 | ❌ | 002 |
| 1' | 签名不匹配 | 伪造 `X-Lark-Signature` | `403` | ❌ | 无 | ❌ | 002 |
| 1'' | 时间戳超窗 | 时间戳 ±(window+1) | `403` | ❌ | 无 | ❌ | 002 |
| 2 | 解密失败 | 错误 Encrypt Key / 坏密文 | `400` | ❌ | 无 | ❌ | 002 |
| 3 | Event 解析失败 | 缺 `header` / `content` 非法 JSON | `200` | ❌ | 无 | ❌（不重推） | 002 |
| 4 | 事件不适用 | 群聊 / 非 text / 非目标事件类型 | `200` | ❌ | 无 | ❌ | 002 |
| 5 | 重复事件 | 同 `event_id` 连发两次 | `200` | ❌（第二次） | 不重复回复 | ❌ | 002 |
| 6 | Session 创建失败 | monkeypatch `resolve` 抛异常 | `200` | ❌ | 兜底文案 | ❌ | 003→004 |
| 7 | Chat Pipeline 异常 | FakeLLM `raise_exc` | `200`（已 ack） | ✅（已进入） | 失败提示文案 | ❌ | 004 |
| 8 | AI 返回为空 | FakeLLM 返回 `[]` / `""` | `200` | ✅ | 兜底文案 | ❌ | 004 |
| 9 | Feishu API 调用失败 | 假传输返回 429/5xx/超时/400 | 不适用（后台） | ✅（已产生） | 本轮丢失 | 429/5xx/超时 ✅；4xx ❌ | 005 |
| 10 | 回复超长 | 注入超长 FakeLLM 输出 | 不适用 | ✅ | 分段到达 | — | 005 |
| 11 | 发送重复 | 同一 `TurnOutcome` 投递两次 | 不适用 | ✅ | 只收到一次 | — | 005 |
| 12 | 用户消息过载 | 并发超过 `FEISHU_SESSION_QUEUE_LIMIT` | `200` | 超限者 ❌ | 过载提示 | — | 004 |
| 13 | 限流（入站） | 同 `open_id` 超过阈值 | `429` | ❌ | 限流提示 | — | 002 |
| **14** | **收件人解析失败**（仅 Proactive） | `resolve_recipient` 返回 `None` | 不适用（无入站） | ❌ | 该用户收不到 | — | 005 |
| **15** | **无锚点且无幂等键**（仅 Proactive） | 调用 `send_proactive` 时不传 `idempotency_key` | 不适用 | ❌ | 无 | — | 005 |
| 附 | 未启用 | `FEISHU_ENABLED=false` | `404` | ❌ | 无 | — | 002 |

**收口的定义**：表中每一行都有 ① 一个产生该条件的测试构造方式、② 一个明确的断言点。**缺任一项即视为未收口。**

### 6.2 静态依赖边界（**本 Task 最重要产出**；本次修订按 architecture §2.2 R1~R5 重构）

> **为什么重构**：原断言写的是"核心层一律不得 import `app.channels.*`"。但终局架构要求**核心能够对"通道"编程**（未来 Autonomy 通过 `channels/base.py` 契约发送主动消息，architecture §2.5.5）。因此禁令必须**从粗粒度收窄为契约/实现二分**——否则要么误伤合法依赖，要么给实现留下后门。

#### 6.2.1 方向一：`app.channels/<impl>/**` 的允许/禁止

| 类别 | 模块前缀 | 判定 |
|---|---|---|
| ✅ 允许 | `app.core.*` | allow |
| ✅ 允许 | `app.channels.*`（含 `base`） | allow |
| ✅ 允许（架构 §2.2 明确例外） | `app.services.channel_identity_service` | **allow（保持例外）** |
| ✅ 允许（架构 §2.2） | `app.services.trace_collector` | allow |
| ✅ 允许（管线入口；实现为 `services/` 下的薄壳） | `app.services.agent_service` | allow |
| ✅ 允许（架构 §2.2「application（管线入口）」） | `app.application.*` **除** `chat_pipeline` / `post_process` | allow |
| ✅ 允许 | `openai`（仅异常类型，与 `api/v1/chat.py` 既有做法一致）、标准库 | allow |
| ❌ 禁止 | `app.character*` | **deny** |
| ❌ 禁止 | `app.services.memory*` / `app.services.world*` / `app.services.state*` / `app.services.relationship*` | **deny** |
| ❌ 禁止 | `app.chains*` | **deny** |
| ❌ 禁止 | `app.repositories*` | **deny** |
| ❌ 禁止 | `app.models*` / `app.prompts*` | **deny** |
| ❌ 禁止 | `app.application.chat_pipeline` / `app.application.post_process` | **deny**（若要读管线常量/锁，视为越界） |
| ❌ 禁止 | `app.api*` | **deny** |
| ❌ **禁止（本次修订新增 R3）** | **任何 Autonomy / Life Loop / Scheduler / Policy 模块**（`app.application.autonomy_engine` / `autonomy_worker` / `life_loop` / `services.autonomy_policy` / `services.proactive_executor` / `services.trigger_evaluator` …） | **deny**（渠道不得干涉"何时开口"） |
| ⚠️ 待定 | `app.core.db` | **allow 但需评审**：仅当 channels 确需 `SessionLocal`（本设计**不需要**——身份读写走 003 的 service）。断言按 **deny** 执行，若实现确需须显式加入 allowlist 并说明 |

**判定实现方式（fail-closed）**：

```text
1. 收集 app/channels/**/*.py 中所有 import 的顶层模块名（含 from ... import ... 的相对/绝对形式）
2. denylist 前缀命中 → 立即失败（最清晰的错误信息）
3. 以 "app." 开头的模块不在 allowlist → 失败（fail-closed：新增依赖必须显式评审）
4. 非 "app." 的第三方模块：仅 openai 在白名单；其余（如 httpx/requests/redis/celery/kafka）命中即失败
```

#### 6.2.2 方向二：核心层不得反向依赖 channels **实现**

| 被扫描目录 | 禁止出现 | 允许出现 |
|---|---|---|
| `app/application/**`（含 chat_pipeline / post_process / world_engine / life_loop / autonomy_*） | `app.channels.feishu`（及任何 `app.channels.<impl>`） | `app.channels.base`（**仅契约**，R2） |
| `app/services/**`（既有域服务 + 新建的 `channel_identity_service`） | `app.channels.<impl>` | `app.channels.base`（`channel_identity_service.resolve_recipient` 返回 `RecipientRef` 需要它） |
| `app/repositories/**` | `app.channels.*`（含 base —— 仓储不需要契约） | — |
| `app/character/**` | `app.channels.*` | — |
| `app/chains/**` | `app.channels.*` | — |
| `app/models/**`、`app/prompts/**` | `app.channels.<impl>` | `app.channels.base`（若模型需引用出站契约类型） |
| `app/core/**` | `app.channels.*`（`base.py` 自身也不得 import `app.*`，R4） | — |

> **例外**：`app/api/**` **允许** import `app.channels.*`（含实现）——`api/v1/feishu.py` 是传输层（架构 §2.2 规定 `api → channels`）。因此方向二的扫描**排除 `app/api`**。
> **例外**：`app/main.py`（组合根）允许 import `channels.<impl>`（未来若需在 lifespan 启动出站循环）。

#### 6.2.2b 方向三：`channels/base.py` 的依赖面（**本次修订新增**）

```text
[ ] base.py 只 import 标准库（零第三方依赖）
[ ] base.py 不 import 任何 app.* 模块（零内部依赖）
```

理由（R4）：`base.py` 是被**核心层**允许 import 的最底层契约。若它带上 HTTP / 重试 / 飞书字段或任何 `app.*` 依赖，核心就被间接污染，"契约"退化成"实现"。这条断言是 R2 放开后**唯一**的守门机制，必须常驻。

#### 6.2.3 实现要点（AST 而非正则）

```text
用 ast.parse 读取源码，ast.walk 收集 ast.Import / ast.ImportFrom：
  - ImportFrom 的 module 可能为 None（纯相对导入 from . import x）→ 需结合包路径还原；
    实现上：只要求解析「绝对模块名」，相对导入按所在包回溯（或直接禁止相对导入跨包）
  - 动态导入（importlib / __import__）也要扫：匹配字符串字面量里的模块名
  - ★ 不得 import 被测模块来检查（否则"检查动作"本身会执行副作用）
测试自身用 pathlib 遍历 + ast 解析，纯 CPU，无 IO 依赖
```

- **常驻性**：该测试**不能**放在 `SLOW_TEST_FILES`，也不能依赖 DB / 网络 → 属 `tests/unit/`，每次 Fast Test 都会跑。
- **失败信息**：必须报"文件路径 + 行号 + 违规模块"（否则修复者要自己找）。

### 6.3 未启用零路径（`FEISHU_ENABLED=false`）

四类计数**全部为 0**：

| 计数项 | 观察方式 |
|---|---|
| HTTP 请求（任何） | 假传输 `calls` 长度 == 0（且 transport 未被构造） |
| `tenant_access_token` 获取 | 001 的 `token_view().has_token is False` |
| 调用 `agent_service.stream_chat` | monkeypatch 计数 == 0 |
| DB 写（`channel_identities` / `conversations`） | 表行数 == 0 |

外加：`POST /api/v1/feishu/events` → `404`。

> **要点**：不仅断言"路由不可用"，还要断言"**没有任何副作用**"——这是架构 §5.2「未启用即隐身」的完整含义。

### 6.4 多用户隔离回归（`test_feishu_isolation.py`）

对 `open_id = ou_A` / `ou_B` 各跑一轮真实链路（FakeLLM 可编程为不同回复），然后**交叉断言**：

| 资源 | 断言 |
|---|---|
| Conversation | `conversations.id` 分别为 `feishu:ou_A` / `feishu:ou_B`；`user_id` 对应；互查为空 |
| Messages | A 的会话消息数 == 2；B 查 A 的会话为空 |
| Memory | A 写入记忆后，`memory_repository.list_by_user("feishu:ou_B")` 为空 |
| World / Inventory | `world_repository.world_id_for("feishu:ou_A") == "home:feishu:ou_A"`；A/B 世界为不同行；A 的实体不出现在 B 的 `list_objects` |
| Relationship | `relationship_state` 按 user_id 分行；A 的 intimacy 变化不影响 B |
| Character State | `character_state` 按 user_id 分行；A 的 mood 不影响 B |
| **并发** | A 与 B **同时**各发多条 → 各自的 conversation 行数与回复一一对应，无交叉（★ 用户要求的 `A ≠ B`） |

**六项 + 并发**是"多用户"从设计假设变成运行事实的**唯一证据**（架构 §1.1 的收益 #2）。

### 6.5 场景矩阵（`test_feishu_cases.py`）

见 §12.2 的完整清单（正常 / 空 / 超长 / 重复 / 群聊 / 非文本 / 加密 / 非加密 / 认证三连 / 管线异常 / 出站失败 / 过载）。

### 6.6 人工冒烟清单（`regression-checklist.md`）

**实现本 Task 时创建**（本次 Detail 生成阶段不创建，§15.4）。必须包含：

```text
准备
[ ] 飞书开放平台：创建应用 → 申请 im:message + im:message:send_as_bot → 订阅 im.message.receive_v1
[ ] 配置回调 URL：https://<公网域名>/api/v1/feishu/events（内网穿透或测试环境）
[ ] 配置 Verification Token / Encrypt Key；把凭据写入 .env（不提交）
[ ] 数据库：alembic upgrade head（确认 0036 已应用）
[ ] 启动服务；确认日志无 SettingsError；确认 FEISHU_ENABLED=true

主链路（真模型）
[ ] 飞书单聊发"你好" → 数秒内收到角色回复（一条完整文本）
[ ] 回复内容符合角色人设（非通用助手口吻）——**真模型抽查项**
[ ] 连续 3 轮对话 → 上下文连贯（追问前文能被正确回忆）
[ ] 重启服务后再发一条 → 会话延续（同一 session_id，多轮不断裂）

状态保持（真模型抽查项）
[ ] 说到偏好（如"我讨厌香菜"）→ 下一轮提及相关话题时角色记得（Memory）
[ ] 提到家中物品/消耗行为 → /debug 或 DB 中 worlds/world_entities 发生变化（World/Inventory）
[ ] 关系推进信号（如表达感谢）→ relationship_state 有变化

边界（负例）
[ ] 群聊里 @机器人 → **不回复**（日志有"忽略群聊"记录）
[ ] 发送图片 → **不回复**
[ ] 发送纯空白 → **不回复**
[ ] 同一事件被飞书重推（可用工具重放）→ 只收到一次回复
[ ] 伪造 token / 篡改签名 → 401/403，且**不产生任何回复**
[ ] 关闭 FEISHU_ENABLED 后发消息 → 端到端静默（无回复、无异常日志堆栈）

多用户
[ ] 第二个飞书账号（open_id 不同）对话 → 两账号的上下文/记忆/世界**互不串**
[ ] 两账号同时发消息 → 各自回复正确、顺序正确
[ ] 查 channel_identities → 恰好两行，internal_user_id 分别为 feishu:ou_A / feishu:ou_B

运维
[ ] 限流：同账号快速连发超过阈值 → 收到限流提示
[ ] 关闭飞书应用权限或伪造密钥 → 日志出现明确错误分类（可定位）
[ ] 日志中**不出现** app_secret / encrypt_key / tenant_access_token
```

### 6.7 排障可见性（可选、最小）

| 选项 | 内容 | 建议 |
|---|---|---|
| **A（默认，零改动）** | 复用既有 observability trace：飞书轮次与 Web 轮次同构（002 建 trace → 管线 attach），`/debug/turns/{turn_id}/trace` 可直接查 | **推荐** |
| B（可选） | `api/v1/debug.py` 增只读查询：最近 N 条 `channel_identities` / 去重表统计 / 投递失败计数 | 仅当 A 不足以排障时 |

> 若采用 B：**只读**、不新增写路径、不改既有响应模型；且 `debug.py` 已存在属既有文件（改动需登记）。

## 7. Interfaces

| 能力 | 输入 | 输出 | 语义 |
|---|---|---|---|
| 边界扫描（方向一） | `app/channels/**/*.py` 源码 | 违规列表 | AST 解析；失败即报 文件+行+模块 |
| 边界扫描（方向二） | 核心层各目录源码 | 违规列表 | 同上 |
| 场景构造器 | 场景名 | HTTP 响应 / 表状态 | 测试内部工具函数 |
| 零路径计数 | 无 | 四类计数 | 测试内部工具函数 |
| 隔离断言器 | 两个 `open_id` | 六项交叉断言 | 测试内部工具函数 |

**测试工具函数的归属**：放在测试文件内（或 `tests/conftest.py` 的局部 fixture），**不得**在生产代码里为测试加钩子（除 001~005 已定义的 `reset_*` 接缝）。

## 8. Data Model

**N/A** —— 本 Task 不新增任何持久化结构。它只读取既有表（`conversations` / `messages` / `memories` / `worlds` / `relationship_state` / `character_state` / `channel_identities`）用于断言。

## 9. Error Handling

### 9.1 错误传递的端到端一致性（用户要求的重点检查之一）

```text
Webhook（002）      401 / 403 / 400 / 429 / 404   ← 与飞书的契约（必须准确）
   │  （校验通过）
   ▼
Adapter（004）      TurnOutcome.error_kind ∈ {None, empty_response, llm_error, pipeline_error,
                       identity_error, incomplete, overloaded}
   │                ← 这里的错**不再产生 HTTP 码**（已 ack），只转化为"给用户的话"
   ▼
Pipeline（既有）     EmptyLLMResponseError / APIStatusError / Exception   ← 三类既有语义
   │
   ▼
Outbound（005）     投递失败 → 只记日志（不冒泡、不改变 error_kind、不回滚）
```

**一致性断言**：

| 断言 | 说明 |
|---|---|
| 004 的 `error_kind` 覆盖既有三类 | `llm_error` / `empty_response` / `pipeline_error` 与 `api/v1/chat.py` 的三类一一对应（§004 §6.7 表） |
| **不新增第四套业务错误体系** | 飞书特有的两类（`identity_error` / `overloaded`）是**渠道边界情况**，不进入核心错误模型 |
| 005 的失败**不改变** 004 的判定 | 出站失败与"回复是否生成"无关；`TurnOutcome` 不被回写 |
| 任何一层失败都不产生 5xx | 入站路径的所有输入都落 4xx/200（002 §9.2） |
| 用户可见文案恒不含技术细节 | 全链路的 `outbound_text` 断言不含状态码 / 类名 / 堆栈 / JSON 结构 |

### 9.2 错误矩阵的可执行性检查

对 §6.1 的每一行，断言"**存在**一个测试且该测试在错误路径上检查了全部 4 个维度"：

```text
① HTTP 状态码（入站类）
② 是否调用后续环节（管线 / 投递）——用 monkeypatch 计数
③ 用户可见结果（收到什么 / 什么都没收到）
④ 是否重试（假传输调用次数）
```

**缺第 ④ 维度的行**：入站 1~5、13（入站不重试，应断言"请求次数 == 1"）。

## 10. Concurrency / Idempotency

| 场景 | 断言 |
|---|---|
| 同 `event_id` 并发（002 去重） | 恰好 1 次派发 |
| 同 `open_id` 首次并发建身份（003） | 恰好 1 行、返回值全等 |
| 同 `session_id` 并发多轮（004） | 严格 FIFO、无上下文交错 |
| 不同 `session_id` 并发（004） | 互不阻塞（A 慢不拖 B） |
| 同 `TurnOutcome` 重复投递（005） | 总请求次数不翻倍 |
| **A/B 并发全链（006 新增）** | 六项资源互不污染（§6.4） |
| 队列过载 + 后续恢复 | 过载不影响后续正常处理；计数归零 |

**并发测试的确定性要求**：使用可编程延迟的 FakeLLM/假传输制造重叠，**禁止**用裸 `sleep` 赌竞态；等待用 `conftest.wait_until`（TESTING.md §6）。

## 11. Security

### 11.1 敏感面审计清单（用户要求的重点检查之一）

| 敏感项 | 允许出现的位置 | 禁止出现的位置（断言） |
|---|---|---|
| `FEISHU_APP_SECRET` | `.env` / 进程环境 / `FeishuSettings` 内存 / 出站请求体（仅 token 端点） | 源码字面量、日志、异常、trace、测试输出、`regression-checklist.md` |
| `FEISHU_ENCRYPT_KEY` | 同上 + 签名计算 | 同上 |
| `tenant_access_token` | `client.py` 内存 + 出站 `Authorization` 头 | 日志、异常、`TokenView`、`SendResult`、trace |
| `FEISHU_VERIFICATION_TOKEN` | settings 内存 + 比较 | 日志（**比较失败也不打印收到的值**）、异常 |
| 原始 body / 密文 / 明文 payload | 内存 | 日志（只记 `len`）、异常 `detail` |
| 用户消息 / AI 回复全文 | 管线（对话历史，不可避免） | 飞书链路的日志（受 `log_content_preview_chars` 控制） |
| `open_id` / `message_id` / `chat_id` | 日志（排障必需） | —（非凭据） |

**断言方式**：`caplog` 全量文本 + 异常的 `str()` / `args` 双重检查；跨 Task 覆盖（002 的 401/403 路径、003 的 DB 异常、004 的管线异常、005 的投递失败）。**每个 Task 的脱敏断言在 006 统一复核一遍**。

### 11.2 安全默认拒绝的回归

```text
[ ] 校验未通过 → 零业务副作用（不含"先写日志再校验"的顺序错误）
[ ] 未启用 → 端点 404 + 零副作用
[ ] 群聊 → 一律忽略（不因"只有一个人说话"而放行）
[ ] 伪造/篡改的请求无法触发任何 LLM 调用（成本保护）
```

## 12. Testing

### 12.1 `tests/unit/test_feishu_boundary.py`（★ 常驻守门）

```text
方向一（channels → 外部）
[ ] app/channels/** 无 app.character / app.repositories / app.chains import
[ ] 无 app.services.memory*|world*|state*|relationship* import
[ ] 无 app.models / app.prompts / app.api import
[ ] 无 app.application.chat_pipeline / app.application.post_process import
[ ] ★ R3：无任何 Autonomy / Life Loop / Scheduler / Policy 模块 import
      （application.autonomy_engine / autonomy_worker / life_loop / services.autonomy_policy /
        services.proactive_executor / services.trigger_evaluator …）
[ ] app.channels 的 "app." import 全部落在 allowlist 内（fail-closed）
[ ] 无 redis / celery / kafka / pika / httpx / requests import（项目禁用新增基础设施）
[ ] 允许项不误报：channel_identity_service / trace_collector / agent_service / core.* / openai
[ ] 失败信息包含 文件路径 + 行号 + 违规模块名

方向二（核心 → channels）
[ ] ★ R1：app/application/** 无 app.channels.<impl>（如 app.channels.feishu）import
[ ] ★ R1：app/services/** 无 app.channels.<impl> import
[ ] app/repositories/** / app/character/** / app/chains/** / app/core/** 无 app.channels import
[ ] app/models/**、app/prompts/** 无 app.channels.<impl> import
[ ] ★ R2（反向断言，防误伤）：app/services/channel_identity_service 允许 import app.channels.base
      —— 断言该 import 存在且**不**被判为违规（证明 allowlist 生效，不是"一刀切"）
[ ] ★ R2：构造临时文件 import app.channels.base → 不报错；import app.channels.feishu → 报错
[ ] app/api/** 被排除（允许 api → channels，含实现）
[ ] app/main.py 被排除（组合根允许 import impl）

方向三（base.py 依赖面，本次修订新增）
[ ] ★ R4：app/channels/base.py 只 import 标准库（零第三方依赖）
[ ] ★ R4：app/channels/base.py 不 import 任何 app.* 模块（零内部依赖）
[ ] 负例自检：把一段 `import httpx` / `from app.core.settings import get_settings`
      注入临时副本 → 断言扫描器确实报错（防"断言永远为真"的假绿）
```

### 12.2 `tests/integration/test_feishu_cases.py`（场景矩阵）

```text
正常
[ ] text → AI → reply：200；reply 请求 1 次；messages +2

空
[ ] AI → 空（FakeLLM response=[]）：用户收到兜底文案（非空）；messages +2（管线已保存空回复？——
    断言以管线既有行为为准：若管线未保存/保存空串，均以实测为准并固化期望）

超长
[ ] AI → > FEISHU_MAX_REPLY_CHARS：多段顺序发送；"".join(parts) == normalize(text)；无丢字无重复

重复
[ ] 同 event_id 两次 → 派发 1 次、回复 1 次

群聊
[ ] chat_type=group → 200、0 次管线、0 次投递

非文本
[ ] message_type=image / file / audio / post → 200、0 次管线
[ ] （顺带）text 事件但 content 为卡片结构 → 200、0 次管线

加密
[ ] 加密 webhook 正确解密 → 全链成功（**方案 A 已冻结：正式支持加密事件**，真实 crypto path）
[ ] 非加密 webhook（无 encrypt 键）→ 全链成功
[ ] Encrypt Key 为空 + 收到 encrypt → 400、0 次管线

认证
[ ] invalid token → 401、0 次管线
[ ] invalid signature → 403、0 次管线
[ ] expired timestamp → 403、0 次管线

管线
[ ] LLM 异常（raise_exc）→ 失败文案、出站 1 次、messages 不增（无半成品）
[ ] 流异常（中途抛错）→ pipeline_error 文案
[ ] 流不完整（有 token 无 done）→ 已累积内容被发送 + error 日志

飞书 API（出站）
[ ] 429 → 重试至上限 → 终败只记日志
[ ] 500 → 同上
[ ] timeout → 同上
[ ] 400 → 不重试（1 次）
[ ] 403 → 不重试（1 次）

过载
[ ] 超过 FEISHU_SESSION_QUEUE_LIMIT → 超限者收到过载提示、未调管线；随后恢复正常

隔离
[ ] 见 §6.4 专项文件（本文件跑单用户路径）
```

### 12.2b `tests/integration/test_feishu_proactive.py`（**本次修订新增**）

> **目的（用户要求）**：验证"已知 `internal_user_id` 可以正确解析到飞书 `external_id`，并发送消息"。**不需要真的实现 Autonomy**。

```text
出口能力（模拟未来 Autonomy 的调用）
[ ] 经 003 建身份：open_id=ou_A → internal_user_id=feishu:ou_A
[ ] 调 send_proactive("feishu:ou_A", "在吗？", idempotency_key="k1")
    → 假传输收到 1 次 send，receive_id_type=open_id、receive_id == "ou_A"
    → 断言：receive_id 与 internal_user_id **不相等**（证明经过身份表解析，而非字符串截取）
[ ] 未知 internal_user_id → 零请求 + ok=False + error=not_found
[ ] 无 idempotency_key → 零请求 + ok=False + error=invalid_request
[ ] idempotency_key 复用（同 key 两次）→ 总请求 1 次
[ ] 不同 idempotency_key（k1/k2）→ 各 1 次

与核心的隔离
[ ] send_proactive **不创建** conversation、**不写** messages（纯出站）
[ ] send_proactive 前后 memories / worlds / relationship_state 行数不变
[ ] 投递失败（500 × max_attempts）后仍满足上述"零写入"断言

无 Autonomy 参与（架构 §2.5.5）
[ ] 全流程中 Autonomy / Life Loop / Scheduler / Policy 模块**未被调用**
      （可对相关模块打桩并断言调用计数 == 0）
[ ] 出站路径**不读取** Autonomy 状态（无 import、无 attribute 访问）

多用户
[ ] ou_A 与 ou_B 各一次 → 各自 receive_id 正确、互不串
```

### 12.3 `tests/integration/test_feishu_isolation.py`

见 §6.4 的七行（六项资源 + 并发）。

### 12.4 `tests/e2e/test_feishu_disabled.py`

```text
[ ] FEISHU_ENABLED=false → POST /api/v1/feishu/events == 404
[ ] 四类计数全 0（HTTP / token / 管线 / DB 写）
[ ] 既有 Web 路径仍正常：POST /api/v1/chat/message == 200（证明"飞书关掉不影响 Web"）
[ ] 服务启动日志无飞书相关 SettingsError
```

### 12.5 既有 Web 回归（用户要求的重点检查之一）

```text
[ ] pytest tests/unit tests/e2e -m "unit or api" 全绿（Web 路径零改动 → 应恒为绿）
[ ] git diff 证明：api/v1/chat.py / api/v1/schemas.py / application/chat_pipeline.py 零改动
[ ] git diff 证明：character/** / services/**（既有域服务）/ repositories/**（既有）零改动
```

### 12.6 执行级别

```text
Focused → Module（tests/unit + tests/integration + tests/e2e 的飞书相关文件）
        → Integration（-m integration，DB 相关）
        → Fast（-m "(unit or api) and not slow"）
        → 【阶段收口】Full Test（本 Task 是 P0 链收口，属 TESTING.md §4 允许 Full Test 的时机）
```

> Full Test 前按 TESTING.md §4 要求**先汇报测试规模**。

## 13. Acceptance Mapping

> 对齐 [../tasks.md](../tasks.md) FEISHU-006 的 7 条 AC。

```text
[ ] §6.1 十五类错误逐条断言：触发条件 / HTTP 返回 / 是否调管线 / 用户可见结果 / 是否重试   (AC-1)
[ ] 场景矩阵全绿：正常 / 空 / 超长 / 重复 event_id / 群聊 / 非 text / 加密 / 未加密 /
    验签失败 / 解密失败                                                                (AC-2)
[ ] 多用户隔离回归：两个 open_id 并发对话互不串（会话 / 记忆 / 世界 / 库存 / 关系 /
    角色状态六项逐项断言）                                                              (AC-3)
[ ] ★ 依赖边界静态断言常驻，按 R1~R5 分开断言（本次修订重构）：
     方向一 channels.<impl> 禁止 import 列表命中即失败（含 R3：Autonomy 家族全禁）
     方向二 核心层禁止 import channels.<impl>，但允许 channels.base（R1/R2；含"允许项不误报"反向断言）
     方向三 channels/base.py 零第三方依赖、零 app.* 依赖（R4）
     负例自检：注入违规模块能确实报错（防假绿）                                          (AC-4)
[ ] FEISHU_ENABLED=false 全链路零路径（网络 / token / 管线 / DB 写 四类计数均为 0）        (AC-5)
[ ] 全部测试确定性、`pytest -m "not slow"` 快速通过；测试文件命名全局唯一（xdist 兼容）    (AC-6)
[ ] docs/integrations/feishu/regression-checklist.md 人工步骤可执行（配置回调 URL → 发文本
    → 收到回复 → 二次对话验证记忆延续 → 群聊不响应 → 关闭开关后端到端静默），含真模型抽查项 (AC-7)
[ ] ★ Proactive 出口能力验证（本次修订新增）：已知 internal_user_id → resolve_recipient →
    external_id → send 成功；未知 ID → 零发送；无 idempotency_key → 拒绝发送；
    全流程无 Autonomy 参与（调用计数 == 0）
[ ] 既有 Web 路径零回归（api + unit 全绿；chat.py / schemas.py / chat_pipeline.py 零 diff）
[ ] 敏感面审计通过（app_secret / encrypt_key / verification_token / tenant_access_token /
    signature 在日志与异常中零出现）
[ ] 设计文档状态：Risk #1 已统一为**方案 A**（无"二选一/待决策/暂不支持加密"表述）；
    Risk #2 已明确 **Deferred 且不阻塞**（无 Push/Pull、Registry、组合根、adapter 生命周期的实现）
```

## 14. Out of Scope

| 不做 | 理由 |
|---|---|
| 任何新功能（含群聊、Streaming、卡片、图片/文件/语音） | 架构 §7.2 明确不做 |
| **Autonomy / Scheduler / Desire / Decision / Life Loop / Proactive Policy / 主动消息触发方** | 本次只验证**出口能力**（`internal_user_id` 可解析并发送），**不实现触发方**（用户明确要求） |
| 为主动消息新增 schema（外部推送态载体） | 未来任务；需先决策（architecture §2.5.6） |
| Web ↔ 飞书账号绑定 | 架构 §7.2 明确不做 |
| 真实飞书 API 调用 / 真实 LLM 调用（自动化测试中） | TESTING.md §2 / §5 硬约束 |
| 修改 002~005 的**实现逻辑** | §4 红线：收口 Task 不得成为被验收对象（仅允许修被测试暴露的缺陷） |
| 修改 `FEISHU-001.md` | 属 FEISHU-001 自己的 Task；006 不得改其**实现逻辑**。注意：001 的**文档**已获授权同步 Risk #1（crypto 依赖）——那是 001 的文档修订，不是 006 的动作 |
| CI 接入 / 流水线配置 | 项目当前无 CI（TESTING.md §7），非本 Task 范围 |
| 性能压测 / 容量规划 | 第一阶段单实例、单用户量级；`test_performance` 类护栏非本次要求 |
| 分布式去重 / 多 worker 一致性 | 架构与各 Detail 已明确为"接受的范围限制" |

## 15. Implementation Notes

### 15.1 收口 Task 的独立性原则

006 的最高风险不是"漏测"，而是**变成"改实现让测试通过"**。执行纪律：

```text
1. 先写测试（含边界断言），再看结果
2. 测试失败时，先判断"是测试写错了"还是"实现真有缺陷"
3. 只有确认是缺陷时才改 app/channels/**，且必须记录改了什么、为什么（写入 PR 描述）
4. 不得为了让断言通过而放宽断言（尤其是边界断言与脱敏断言）
5. 不得修改前序 Task 的 Detail 文档来"对齐"实现（应反向修正实现）
```

### 15.2 静态边界断言的实施建议

- **先写方向二（反向依赖）**：它会立即暴露 004 若误用 `application.post_process` 锁之类的问题，反馈最快。
- **再写方向一**，并按 §6.2.1 的 allowlist 逐项放行（每放行一项都要有架构依据引用）。
- 断言失败信息格式：`f"{file}:{lineno} 违规 import: {module}"`。
- **不要**用 `grep`/正则实现（会被 `from app import character` 之类的变体绕过，也会被注释/字符串误伤）；必须 AST + 动态导入字面量扫描。

### 15.3 设计文档回填状态（**本次架构修订已回填 2 项**）

| 事项 | 来源 | 状态 |
|---|---|---|
| `app/core/db.py` 进入改动白名单 | FEISHU-003 §15.1 | ✅ **本次已回填**（tasks.md 头部白名单） |
| 过载策略冻结为"拒绝最新"（架构原文"丢弃最旧"） | FEISHU-004 §15.3 | ✅ **本次已回填**（architecture.md §6.2 #12 已改写） |
| 加密事件支持的依赖决策 | FEISHU-002 §15.1 | ✅ **已决策并回填**：Risk #1 = **方案 A**（引入 `cryptography`，正式支持 Encrypt Key）；architecture.md §5.1 / §6.2 #2 / §6.4 已同步 |
| `api/v1/debug.py` 是否进入白名单（006 可选排障端点） | FEISHU-006 §6.7 | ⬜ 未决——仅当启用 §6.7 的"排障端点"选项时需要；**与 Risk #1 crypto 决策无关** |
| **（新增）出站触发方如何拿到 adapter 实例** | architecture §2.5.6 | ⬜ 未决——Autonomy 立项时决策（候选 A/B） |

> 本次修订（支持主动消息）已获得用户对 architecture.md / tasks.md 的**显式修改授权**，故上表前两项已直接回填。剩余三项是**实现期/未来立项**的待办，也是本 Task 收口报告必须回答的问题。

### 15.4 `regression-checklist.md` 本次不创建

用户本轮要求"只生成 FEISHU-002~006 五个文件"，而 tasks.md AC-7 要求 `regression-checklist.md`。二者不冲突：**该清单是 FEISHU-006 实现阶段的交付物**（创建时机 = 实现本 Task 时），本轮 Detail 只定义其**必须包含的条目**（§6.6）。因此本轮**不创建**该文件，避免超出用户指定的文件集合。

### 15.5 测试命名的 xdist 兼容

项目默认 `-n auto --dist loadgroup`。因此：

- 测试文件与用例名**全局唯一**（禁止多个文件定义同名 `test_ok`，pytest 不要求唯一但 xdist 分组/报告可读性依赖唯一性）。
- 需要真实 PostgreSQL 的用例归入 `xdist_group("migration")`（既有机制）。
- 新增慢测试（如包含本地 server 线程）加入 `SLOW_TEST_FILES`。

### 15.6 Implementation Order

```text
 1. 边界断言：先方向二（反向依赖），再方向一（allowlist 逐项）
 2. 未启用零路径（e2e）——最快暴露"import 期副作用"的问题
 3. 场景矩阵（integration）：正常 → 空 → 超长 → 重复 → 群聊 → 非文本 → 认证 → 管线 → 出站
 4. 加密/解密用例（**方案 A 已冻结：真实 `cryptography` path**，禁止 monkeypatch 假解密）
 5. 隔离回归（六项 + 并发）
 6. 敏感面审计（caplog 全量 + 异常串，跨 Task 复核）
 7. 既有 Web 回归（api + unit）
 8. 人工冒烟清单（创建 regression-checklist.md）
 9. Focused → Module → Integration → Fast →【阶段收口】Full Test（先汇报规模）
10. 收口报告：回答 §15.3 的三处回填问题 + 给出 P0 链完成度结论
```
