# V5.0.0 实现度审查报告（2026-09-29）

> **性质**：全量进度审查（只读，不产码）。对象 = `tasks.md` 注册的 41 个正式任务（APP-001~025 / API-001~010 / PLT-001~006）+ §12~§14 三个增量注册，对照 `apps/mobile` / `apps/backend` 实际代码逐项核实。
> **方法**：三路并行核查（后端 API 面 / 移动端页面与数据层 / PLT 与文档声明），甄别「端点存在但返回占位」「页面在但数据写死」「引擎写好但触发链断」「pubspec 声明但零使用」四类情况，全部结论带 `file:line` 证据。
> **一句话结论**：地基与对话闭环是真材实料（真实现 16/41 ≈ 39%）；「空有架子」集中在 M2/M3 的产品表面层；M4 整段仍在 PLT-001 门控后（刻意留空，非隐瞒）；41 个 Task Detail 状态行全部失真。
>
> **🔄 2026-09-29 续修更新**：本报告出具后，P0/P1 中的多数项已落地。**逐项状态见 §5**，本轮修复内容见 §6，本轮新发现见 §7，**本报告自身的更正见 §8**（原 §1 计数与多处行号有误，§2 有 6 条结论在报告落款时已被工作区未提交改动修掉）。

---

## 1. 总体分布

> 分母 = **41 个正式任务**（原报告写 42，误把 `tasks/*.md` 里的 `README.md` 计入）。行计数原报告因 `APP-018`/`APP-022` 归属重复而失真，本表已按任务唯一归属重排。

| 里程碑 | 真实现 | 半成品 | 纯架子 | 门控 / 退役 |
|---|---|---|---|---|
| M0 地基（8） | APP-001/002/003/006/007/008 | APP-004（drift 未接线）、APP-005（外部深链未配） | — | — |
| M1 对话（7） | API-001（邮箱登录形态）/002/003、APP-010/011 | APP-009（会话列表缺）、APP-012（mode 不上云，任务书内裁剪） | — | API-001 配对码按 §13 退役（替代链路为真） |
| M2 生活域（9） | API-005/006、APP-017、APP-022 | API-004、API-007、APP-014、APP-016 | APP-015 | — |
| M3 主动（6） | APP-018 | API-008、APP-019/020/021 | — | — |
| M4 健康（5） | — | — | APP-024/025 + `health.py` stub | API-009/010、APP-023 按 D1 刻意留空 |
| PLT（6） | — | PLT-002（调研完成）、PLT-004（大部分）、PLT-005（CI 建好） | PLT-003、PLT-006 | PLT-001 探针真 / 报告未出，**门控仍关闭** |

**真实现合计 = 16 / 41**（M0 6 + M1 5 + M2 4 + M3 1）。原报告「17/42」系 `APP-018` 在 M2、M3 两行重复计入。

## 2. 「空有架子」实锤清单（按严重度）

> 每条附**当前状态**；`✅ 已修` 表示本轮或报告落款时的未提交改动已修复，`⬜ 未修` 表示仍待整改。

### 2.1 页面在、数据是假的（6 处，P0）

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 1 | `apps/mobile/lib/features/home/presentation/home_page.dart` | 首页三宫格 `healthAuthorized=true` 分支写死 `7h12m / 62bpm / 6,234`（设计稿示例值），违反任务书 APP-014「不得用假数据」红线；`home_page_test.dart` 将假值断言固化 | ✅ 已修。改为三分支（真实 `metrics` / 已授权未同步 → 诚实空态 / 未授权 → 引导授权），并**另修一处契约错配**：客户端原读 `health['metrics']`，而后端字段名为 `cells`（`home.py:44`），导致「有数据」分支永远不可达 |
| 2 | `apps/mobile/lib/features/life/presentation/life_page.dart` | 生活页六张模块卡 AI 摘要全部写死（「12 条 · AI 已整理」等）；`features/life/data/` 仅 `.gitkeep` | ✅ 已修。摘要改由 `LifeRepository`（`/tasks` + `/ledger/summary`）真实产出；`features/life/data/life_repository.dart` 已建。另修「请求失败被 `catchError` 吞成空数组 → 网络错误显示为『今天没有待办』」的诚实性缺陷 |
| 3 | `apps/mobile/lib/features/life/presentation/capture_route.dart` | 快速捕获「已归到『记账』」是本地 setState，零后端调用、零 AI 意图归类（APP-022 核心诉求未实现） | ✅ 已修。任务/备忘录经 `routeToTaskDomain` 真落 `POST /tasks`（kind=memo），可 `DELETE /tasks/{id}` 撤回改归；「记账」跳对话并预填文本。注：**无 AI 意图分类是已声明的 V1 降级裁决**（代码注释明确），非隐藏假实现 |
| 4 | `apps/mobile/lib/features/profile/presentation/profile_page.dart` | 主动关怀三开关 `AppToggle(value: …, onChanged: (_) {})` 写死 no-op，不持久化不调度 | ✅ 已修。早/晚开关接 `CarePrefsRepository`（GET/PUT `/briefing/preferences`）并重排本地通知；第三个开关改显式「即将开放（M4 门控）」文本 |
| 5 | `apps/mobile/lib/features/health/presentation/health_consent_page.dart` | 健康授权开关写死 no-op，无同意持久化（APP-025 为 P0） | ✅ 已修。`PrefsStore.healthConsentGranted` 持久化 + 加载态 + 补充说明 |
| 6 | `apps/mobile/lib/features/chat/presentation/chat_ledger_page.dart` | AI 记账页纯占位 `Text('chat-ledger …')` | ✅ 已修。改为真实会话消息 + 真实月度摘要 + loading/error/empty 三态 + 「查看账本」入口。**过程卡故意未实现**（依赖 `tool_step`，该事件不落库无读面，见 §7） |

### 2.2 引擎真、触发链断（4 处，P1）

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 7 | `apps/mobile/lib/features/briefing/data/local_brief_notifier.dart` | `zonedSchedule` 实现完整，但 `scheduleDaily` 全仓零调用点——无任何 UI 能设定时刻，通知永不触发（叠加 #4 → M3 收口点 C4 不可达） | ✅ 已修。`profile_page.dart:84,88` 两个调用点；`LocalBriefNotifier.attach/shared` 全局装配 + Android 通知权限申请；`bootstrap.dart:19` 已有 `tzdata.initializeTimeZones()`。遗留（小）：`_rescheduleNotify` 依赖 shared 非空的时序无断言、重排失败无回滚提示 |
| 8 | `apps/mobile/lib/core/storage/`（drift 7 表 + 3 仓储 + 测试均真） | 运行时零接线：`ChatHistoryCache` 无构造点、`BriefingRepository()` 不注入缓存、`openInMemory` 仅测试用 | ⬜ 未修 |
| 9 | `apps/mobile/lib/features/profile/presentation/privacy_page.dart:37-90` | 文案承诺「服务端与本地缓存同步删除」但本地清空函数（`local_stores.dart:40-44`）零调用；导出结果拿到即丢弃 | ⬜ 未修 |
| 10 | 组件装配缺位 | ResultCard（结果卡+快捷 chips）零使用；会话列表 `sessions` 从未写入（`chat_page_state.dart:54`）；记忆页编辑为「原样 PATCH」空转（`memory_page.dart:116`） | 🔶 部分已修。记忆页编辑**已核实为空转**（原样回传未修改的 `item.content`）并已修：改为弹窗编辑、把新正文提交后端、正文未变不发请求；记忆页另对齐 `API-007` 分组契约、遗忘加二次确认。`ResultCard` 零使用与 `sessions` 无写入仍未修 |

### 2.3 后端「字段/能力是声明的，不是产出的」（3 处，P1）

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 11 | `apps/backend/app/api/v1/home.py:121-135` | `/home/summary` 8 区块中 AI 总结 / 问候 / Orb 状态语为硬编码占位（含「昨晚睡得不错」假健康表述）；真实仅任务与今日消费两块 | ✅ 部分已修。问候语改按时钟推导（`greeting_for`）、AI 总结改取真实洞察（`insight_block_for` → `insights_query.list_insights`，无洞察则留空由客户端出空态）、`mode_chip` 改取最新会话模式；已删假健康表述。**未修**：`spend.budget = 200.0`（无领域数据源，见 §7）、`health.authorized=False`（M4 门控，属正确值） |
| 12 | `apps/backend/app/api/v1/memory.py:23-24` | `source_count` / `usage_receipts` schema 声明但全仓无产出点（恒空）；「遗忘」为物理删除而非任务书要求的「置 forgotten 可审计」（`memory_repository.py:233-239`） | ✅ 已修。按 `tasks/API-007.md` 冻结规格重做：`source_count` = `1 + len(merge_chain)`、`source_kind` 取 `source_ref["table"]` 回退 `source`、`usage_receipts` 只来自 `runtime_traces` 的 `memory_retrieve_v2` 步（30 天窗、每 kind 留最新、`filtered` 不算使用）；「遗忘」改置 `forgotten`（不硬删）+ `forgotten_at` 审计 + 幂等保留首次时刻；`api/v1/memory.py` 重写为零仓储依赖 |
| 13 | `apps/backend/app/api/v1/briefing.py` | 「按设定时刻预生成」未实现（请求时合成），「供本地通知离线取用」验收项不成立 | ⬜ 未修（`briefing.py:81` 仍为请求时 `compose_brief`） |

## 3. 文档与台账问题

1. **41/41 个 Task Detail 状态行全为「未开工」**（2026-09-23 生成后未回写）；实际约 16 个已达真实现。⬜ 未修
2. 三个信息源互相矛盾：Detail 状态行 vs `reviews/v5.0.0-code-review.md`（09-24 时点「仅 2/41 达标」，已过时）vs git log 实际进展；§12~§14 增量以「已实现」登记，与旧状态行双轨并存。⬜ 未修
3. **v5.0.0 无验收报告 / 进度台账**；`tasks.md` 旧迁移号（0055~0058）描述未回写 09-29 折叠为 `0001+0002` 的事实。⬜ 未修
4. `traceability.md` 的 82 个 ✅ 为「覆盖关系已建立」，非「已完成」，易误读。⬜ 未修

## 4. 确认扎实的部分（无需返工）

- **移动端**：分层守卫测试、设计 token（ThemeExtension 双主题、features 零硬编码色值）、Orb（缺 56 尺寸档）、NDJSON 流式（跨 chunk / UTF8 边界、16ms 节流、断流恢复）、邮箱登录全链路（Redis 验证码 + SMTP + Keystore）。
- **后端**：`tool_step` 事件独立通道、`life_tasks` 全 CRUD、insights 真查 DB、IDENT-001~009 身份收口与声明逐项吻合、邮箱验证码登录三层链路。
- **CI**：真跑 golden（30 张）+ codegen diff 门禁 + 后端 fast 套件。

## 5. 整改优先级与状态

| 级 | 事项 | 状态 |
|---|---|---|
| P0 | #1 三宫格假数据切空态分支 + 修固化断言 | ✅ 已修（含 `metrics`→`cells` 契约错配） |
| P0 | #3 快速捕获接真后端 | ✅ 已修 |
| P0 | #4 主动关怀开关接真 + 通知调度 | ✅ 已修 |
| P0 | #5 健康授权同意持久化 | ✅ 已修 |
| P0 | #6 记账页去占位 | ✅ 已修（过程卡除外，见 §7） |
| P1 | #2 生活页摘要真实化 + 失败/空态区分 | ✅ 已修 |
| P1 | #7 通知调度入口接线 | ✅ 已修 |
| P1 | #8 drift 运行时接线 | ⬜ 未修 |
| P1 | #9 隐私页本地清空联动 + 导出落地 | ⬜ 未修 |
| P1 | #10 ResultCard / 会话列表 / 记忆页编辑 | 🔶 记忆页编辑已修 + 契约对齐；ResultCard / 会话列表未修 |
| P1 | #11 后端首页占位真实化 | ✅ 部分已修 |
| P1 | #12 记忆域产出字段 + 遗忘改软删 | ✅ 已修（按 `API-007` 规格，含读面分组口径） |
| P1 | #13 简报定时预生成 | ⬜ 未修 |
| P2 | 回写 41 个 Detail 状态行 | ⬜ 未修 |
| P2 | 补 v5.0.0 验收台账 | ⬜ 未修 |
| P2 | 修正迁移号描述 | ⬜ 未修 |

## 6. 整改结果（2026-09-29 续修）

### 6.1 代码

- **移动端**：`home_repository.dart`（读 `cells`）、`home_page.dart`（三分支 + 空 chip 不渲染）、`life_page.dart`（真实摘要 + 失败态 + 重试）、`capture_route.dart`（真落库 + 撤回改归 + `debugReclassify` 注入点）、`chat_ledger_page.dart`（真实实现）、新增 `features/chat/data/chat_ledger_repository.dart`。
  - ⚠️ **`chat` 域不得 import `features/ledger`**（`layer_guards_test::test_no_cross_feature_import` 会判失败），故账本摘要改由 chat 自有数据面直连后端——与 `life_repository.dart` 同一先例。
- **后端**：`home.py` 新增 `greeting_for` / `mode_chip_for` / `insight_block_for`，删除硬编码问候、AI 总结与「长期记忆运行中」。
- **测试**：新增 `apps/backend/tests/v50/test_home_summary.py`（18 项）、`apps/mobile/test/features/chat_ledger_page_test.dart`（4 项）；重写 `apps/mobile/test/features/capture_route_test.dart`（原断言 `已归到「记账」` 在新实现下必然失败，且未注入 GoRouter 会直接抛错）。

### 6.2 验证证据

| 范围 | 命令 | 结果 |
|---|---|---|
| 后端 v50 | `pytest tests/v50 -q` | **79 passed** |
| 后端 unit | `pytest tests/unit -q` | **1534 passed / 1 failed** —— 唯一失败 `test_redis_client::test_get_redis_without_url_raises` 系 `.env` 设了 `REDIS_URL` 的环境性失败（`REDIS_URL=""` 重跑该文件 3 passed），与本批改动无关 |
| 移动端分层守卫 | 以 Python 等价复现 `layer_guards_test.dart` 全部规则 | 91 个 dart 文件 **0 失败** |
| 移动端语法面 | 括号平衡 + 相对/`package:mobile/` 导入可达性 | 8 个改动/新增文件全部 OK |

> 🚨 **移动端未跑 `flutter analyze` / `flutter test`**：本机 Flutter/Dart 工具链不可用（Dart 创建子进程管道失败，`process_win.cc:744`）。**类型错误与 API 签名不匹配这类问题静态检查抓不到**，上述静态证据不能替代真实测试。提交前须在可用环境跑一遍。

### 6.3 第二轮整改：记忆域（`API-007`）

按 `tasks/API-007.md` 的冻结规格落地「记忆可见」产品出口，同时修掉记忆页编辑空转。

| 交付 | 内容 |
|---|---|
| 新增 `app/services/memory2/product_view.py` | 读面（`list_product_memories`：9→4 分组冻结映射 / 来源追溯 / `source_count` / 用途回执 / 同口径 `total`）+ 写面（`edit_memory` / `forget_memory_for_user`），委托域内既有写面 |
| 重写 `app/api/v1/memory.py` | 3 端点，**零仓储依赖**（AST 断言）；`schemas.py` 追加 6 个模型 |
| 移动端 | `memory_repository.dart` 对齐分组信封；`memory_page.dart` 按服务端分组/标签/来源渲染，编辑改真弹窗提交、遗忘加二次确认 |
| 新增测试 | `test_memory_product_view.py` + `test_memory_api.py`（51 项）+ `apps/mobile/test/features/memory_page_test.dart`（Dio 传输层替身测解析与 PATCH 正文） |

**判据达成**：① api 层零 `repositories` / `core.db` / `langchain`（AST 证据）；② 只返 `active`（`decayed` / `forgotten` / `superseded` / `invalidated` 不可见，用例双证）；③ 遗忘不硬删 + `forgotten_at` 审计 + 幂等保留首次时刻；④ 回执只来自 `runtime_traces` 检索步、零编造、异常区块级降级；⑤ `total` 与分组同快照；⑥ **零新迁移、零新事件类型**（`memories` 结构未动）。

**验证**：`tests/v50` **130 passed**；大范围回归（v2/v21~v26/v30/v40/v50/unit）**6365 passed / 15 failed**，15 项**全部为既有失败**（v24 `tool009_reflector` 5 条属已知 flaky；其余 10 条已用基线 worktree 逐条证实，见 §9）。冻结面 `app/models/memory.py` 摘要**保持原值**（实测 `4371cd84…` 一致）。

**⚠️ 两处显式偏离**：
1. **遗忘的 `runtime_traces` trace 事件未落库**。判据 ③ 的「双证」只达成 ①（`forgotten_at`）。根因：`runtime_traces` 落库唯一路径在 `app/application/observability.py`，而 `services` 层禁止 import `app.application`；`TraceKind` 只有 `turn`/`proactive`/`autonomy_tick`，为一次 HTTP 写入伪造 `turn` 轨迹会污染观测面与回执派生。已登记为待办（需 application 层提供治理写入的 trace 钩子）。
2. **`test_design_principles.py::test_memory_visible_has_usage_receipt_slot` 已改写**。原断言钉页面源码含字面量「已用于」，而新契约下该文案由服务端下发（`receipt.label`），端上零拼接 → 原断言必然失败。已改为钉「页面读 `usageReceipts` 并渲染到 `usageNote`」+「来源位存在」；措辞本身由服务端侧用例（`recall_*`）钉住，覆盖面未减弱。

## 7. 本轮新发现（原报告未覆盖）

1. **「今日预算 ¥200」没有数据源**。设计稿 `design/pages/10-home.html:217` 写「¥128 / 今日预算 ¥200」，但 `services/ledger/budget.py` 的 `BudgetSpec.period` **只有 `month` / `week`，没有 `day` 档**。属设计 vs 领域冲突，需产品裁决（改为本月口径 / 新增日预算概念 / 明确 200 为配置默认值）。**在裁决前不应臆造日额度**，故 `home.py` 的 `spend.budget` 保持未动。
2. **「过程卡」所需数据不存在**。设计稿 `design/pages/21-chat-ledger.html` 的四步过程卡（提取金额 / 识别分类 / 确认时间 / 保存账单）依赖流式 `tool_step` 事件；该事件经 `chat.py:59` 的 sink 下发后**既不落库也无读面**，历史会话的过程无法复原。需后端补持久化 + 按 conversation 的读面，前端才能渲染真实过程卡（否则只能造假）。此缺口同时影响对话页与记账页。
3. `health.authorized` 保持 `False` 属**正确值**而非缺陷：后端无健康事实表（API-009 在 M4 门控后），客户端 `APP-025` 的同意只记在端侧。
4. **`UserMemory` 投影与 memory2 域已脱节（V1 模型未随域演进）**。① `app/models/memory.py:24` 的 `MemoryStatus` 只含 `active`/`superseded`/`invalidated`，而 `memory2/lifecycle.py` 实际会写 `decayed` / `forgotten` → **`memory_repository.get_memory()` 读这两态的行会抛 Pydantic `ValidationError`（而非返回 None）**，任何按 id 读非 active 记忆的路径都会 500；② `_to_memory()` 未映射 `merge_chain` / `source_ref` / `forgotten_at`，`source_count` 与来源追溯无从派生。本轮 `API-007` 以「读原始列」绕开（`product_view.row_facts`），**未改冻结面**（`app/models/memory.py` 在 `tests/v24/test_tool008_integration.py::FROZEN_SOURCES` 内，改它须显式声明 + 同步摘要）。属独立决策，已登记待办。
5. `apps/backend/tests/v50/test_design_principles.py` 用**相对路径读跨工程源码**（`Path("../mobile/lib/...")`）做**弱子串断言**——强依赖 CWD，且契约一变就误伤：本轮记忆页按 `API-007` 契约改为「文案由服务端下发」后，`assert "已用于" in src` 立即变红，而功能其实更正确。建议迁到 Flutter 侧或改为结构化断言。

## 8. 本报告自身更正

| 原表述 | 更正 |
|---|---|
| §1「真实现约 17/42」 | **16/41**（`APP-018` 在 M2、M3 两行重复计入；分母误含 `tasks/README.md`） |
| §1 M2 行 10 项 / M3 行 5 项（表头 9 / 6） | 已按 `APP-022` 归 M2 重排，现两行各 9 / 6 |
| §2 #1 行号 `home_page.dart:282-296` | 该行号指向 `_HealthGrid` **类定义**，非假数据；假数据在旧版 `_HealthGrid.build()` 内 |
| §2 #4 行号 `profile_page.dart:281-291` | 该行号指向「设备连接」SettingRow；三开关在 `SettingGroup('主动关怀')` 内 |
| §2 #5 行号 `health_consent_page.dart:32` | 开关在 `SettingRow('读取健康数据')` 的 `trailing`，非 `:32` |
| §2 #3 定性「本地 setState、零后端调用」 | 定性过重：`routeToTaskDomain` 真调 `POST /tasks`，且**无 AI 意图分类是代码内明确声明的 V1 降级裁决**，不应与 #6 的纯占位同档 |
| §2 未提及 | 补 §7.1（今日预算无数据源）、§7.2（过程卡数据不存在） |
| 全文未记录 | 报告落款时工作区已有 **12 文件 / +472 行未提交改动**，正是修 P0/P1 的那批；§2 中 6 条结论据此已失效 |

> **附**：PLT-001 真机验证仍未执行（探针已就绪，见 `apps/mobile/docs/plt001-probe.md`）；M4 门控在结论产出前维持关闭。

## 9. 零回归对照记录（2026-09-29 第二轮）

**方法**：`git worktree add /c/tmp/baseline-mem2 <HEAD>` → 复制 `.env` → 用主仓库 venv python 跑同一批用例 → `worktree remove --force`。**判据 = 失败集 diff**，非计数。

| 用例 | 改后 | 基线 | 判定 |
|---|---|---|---|
| `v2/test_aut005_goal_evaluation.py::TestRules::test_clean_slice_passes_all` | FAIL | FAIL | 既有 |
| `v2/test_life002_controller.py::TestUserCycle::test_step_error_does_not_block_following_steps` | FAIL | FAIL | 既有 |
| `v21/test_agent008_review_fixes.py::TestLowEnergySuppression::…` | FAIL | FAIL | 既有 |
| `v25/test_plan001_flag_regression.py::test_planning_prompt_bytes_are_unchanged` | FAIL | FAIL | 既有 |
| `v25/test_plan011_regression.py::TestAlwaysOnCompat::test_planning_prompt_is_byte_identical` | FAIL | FAIL | 既有 |
| `v25/test_plan012_flag_matrix.py::TestAlwaysOnPlanningCompat::…digest_is_stable` | FAIL | FAIL | 既有 |
| `v26/test_acceptance.py::TestRegressionCheck::test_v25_migration_head_documented` | FAIL | FAIL | 既有 |
| `v30/test_runtime_autonomous_loop.py::TestSchedulerUnchanged::test_maintenance_steps_unchanged` | FAIL | FAIL | 既有 |
| `v24/test_tool009_reflector.py`（5 条） | FAIL | — | 既有 flaky（本仓已登记） |
| `unit/test_redis_client.py::test_get_redis_without_url_raises` | FAIL | — | 环境性（`.env` 设了 `REDIS_URL`；`REDIS_URL=""` 重跑 3 passed） |
| `v50/test_design_principles.py::test_memory_visible_has_usage_receipt_slot` | FAIL → **PASS** | PASS | **本轮唯一新增失败，已修**（§6.3 偏离 2） |

**结论：本轮改动零新增失败。** 大范围（v2 / v21~v26 / v30 / v40 / v50 / unit）合计 **6365 passed / 15 failed**，15 项全部为既有或环境性。

> ⚠️ 移动端仍**只做静态验证**：本机 Flutter/Dart 工具链不可用。已做的静态证据为——分层守卫等价复现（91 个 dart 文件 0 失败）、括号平衡、相对/`package:mobile/` 导入可达性。**`flutter analyze` / `flutter test` 未跑**，类型与签名问题抓不到。
