# V5.0.0 朝夕 App（Flutter 客户端）任务拆分

> **上游（需求依据，最优先）**：`docs/version/v5.0.0/requirements-analysis.md`（需求条目化 REQ-xxx、14 条冲突与缺口、可行性裁决、**11 条决策已全部拍定**）——**本注册表之外的任何能力均不得进入 Task Detail**。
> **上游（覆盖核对）**：`docs/version/v5.0.0/traceability.md`（设计稿 119 条要求 → REQ → 任务的**全量覆盖矩阵**，含反向核对：41 个任务全部可追溯到设计稿或调研报告）。**每个 Task Detail 生成前先在该矩阵里找到它的来源条目。**
> **上游（技术方案）**：`docs/version/v5.0.0/flutter-architecture.md`（Flutter 分层、选型、Orb 与设计 token 落地路径）。
> **上游（现状约束）**：`docs/current-system-architecture-baseline.md`；`docs/version/v4.0.0/tasks.md`（九条前提裁决）；`docs/version/v3.0.0/acceptance-report.md`（`CONDITIONAL — NOT RELEASED`）。
> **状态**：Task Registry（任务定义）+ **Task Detail 已生成（41/41）**（2026-09-23，位于 `docs/version/v5.0.0/tasks/`，体例对齐 `docs/version/v4.0.0/tasks/PLA-XXX.md`，撰写规范见 `tasks/README.md`）。索引与生成记录见 **§11**。
> **主干**：41 个任务 / 5 个里程碑 / 3 条任务线（`APP-` 客户端、`API-` 后端补齐、`PLT-` 平台横切）。
> **V5.1 增量（2026-09-30）**：`design/pages/` 新增 10 页 + 改动 2 页，按「记账 → 车辆 → 相册」三期增量注册 **24 个任务**（`PLT-007` / `API-015~020` / `APP-027~043`），见 **§15**；需求依据 `requirements-analysis.md` §2.4 / §3.5 / §4.10~§4.13 / §6.1 / §7.1，覆盖核对 `traceability.md` §13，需求确定件 `reviews/v5.1-requirements-determination.md`。
> **本文档不含代码、不含 DDL、不含 UI 稿。**

---

## 0. 开工前必读：七条前提

### 0.1 前提一：本版本是「新开产品轴」，不是 V4.0.0 的延续

移动端在 `docs/version/v4.0.0/tasks.md:1013` 明确标注「未排期 / PLA-016 Out of Scope」。本版本**不改动 V4.0.0 的任何既有域**，只做三件事：**新增客户端**、**补齐产品级 API**、**新增健康与任务两个域**。

### 0.2 前提二：后端只许新增，不许改动既有域行为

沿用 V4.0.0 裁决 5（Preserve 清单）与裁决 8（运行时采用）：

| 约束 | 具体要求 |
|---|---|
| 零 `repositories` 依赖 | `app/api/**` 已有 26 处反向依赖 `app/repositories`（V4.0.0 记为 L3 债）。**本版本新增 API 必须零依赖** |
| 不加功能开关 | V4.0.0 裁决 9：禁止 `*_enabled` 形态的功能位。新设置只许**参数类字段**（阈值 / 取值 / 文案 / 周期） |
| 不改设置命名 | 无 alias 层 → **env 名 = 字段名大写**，改名必须同批同步部署侧 `.env`；`extra="ignore"` 是静默陷阱 |
| 新事件必须登记 | 新增事件类型须登记 `tests/v30/runtime_contracts.py::EXPECTED_EVENT_TYPES`（未知类型 **fail-closed**） |
| 不得给 `loop_runs.steps` 加键 | `test_agent_loop_core.py` 断言 loop 与 legacy 的 `steps` **键集完全相同** → 工具步骤事件须走**独立通道** |
| 不建第二套 Agent | 新能力一律以 Profile 阶段 / 段本体 / Update-handoff / 域唯一写面 / 既有 trigger 四种姿势接入 |

### 0.3 前提三：迁移纪律

> 🚨 **2026-09-29 迁移链已折叠**：`0001~0058` 全部并入基线迁移 `0001_squashed_full_schema.py`，另加增量 `0002_briefing_preferences.py`；**链尾现状 = `0002`**。本节及 §12~§14 中出现的 `0055` / `0056` / `0057` / `0058` 均为**折叠前的原始编号**（历史记录，保留不改）。**后续新增迁移从 `0003` 起编号。**

| 项 | 内容 |
|---|---|
| 链尾现状 | `0002_briefing_preferences.py`（折叠后；折叠前为 `0058`） |
| 本版本新增 | `life_tasks` 建表已并入基线 `0001`（原编号 `0055_life_tasks.py`，服务 API-005） |
| 其余域 | 健康域若进 V1，追加 `0003+` 增量迁移；否则**零新迁移** |
| **V5.1 新增（2026-09-30）** | **车辆域占用 `0003`**（`revision="0003"`、`down_revision="0002"`，见 §15 / `API-018`）。健康域若届时也进 V1，顺延为 `0004`；**同一批迁移必须串行入链，不得并行改链尾** |
| 🚨 已知陷阱 1 | `op.create_check_constraint` **必须传完整布尔式**（`f"source IN {target_check}"`），不能传值清单 → 曾致 `0045` 在 PG 上 `DatatypeMismatch`、`0052` 不可达 |
| 🚨 已知陷阱 2 | **加一个迁移会打破约 22 个跨版本钉测**（`v23/v24/v25/v26` 中的 `MIGRATION_HEAD` 常量、`test_migration_chain_head_is_still_00NN` 用例名、`SCHEMA_TABLE_COUNT`、`SCHEMA_COLUMNS_DIGEST`）→ 执行前先 `git worktree` 取干净基线测 blast radius |
| 🚨 已知陷阱 3 | `FROZEN_BLOB_SHA_BASELINE` 已空 → 改动 `profiles.py` 的 Profile 表内容会红，属**真语义变更**须显式声明 |

### 0.4 前提四：测试与验证纪律（继承仓库实测经验）

- `tests/conftest.py` autouse `_offline_repos` 把仓储指向离线 SQLite（worker 级文件库）；**测试内不要 `from app.core.db import SessionLocal`**，用 `app.repositories.<x>_repository.SessionLocal`。
- **HEAD 基线不是绿的**（约 21 failed / 6485 passed，集中 `tests/v24`）→ **零回归用「基线对照法」**：备份 → `git checkout --` → 跑 → `cp` 回；判据 = 当前失败集 ⊂ 基线失败集。
- 批量 pytest 统计行会被吞（退出期 `PermissionError`）→ 加 `--basetemp=<每次换名的新目录>`（>50 文件触发 safe-delete 闸）+ `-rf`，路径用 Windows 风格 `C:/...`；`-p no:xdist` 报错时用 `-n0`。
- 新增 `runtime_*` 字段须登记 `tests/v30/runtime_support.py::V30_RUNTIME_FIELDS`。
- 跑 PG 用例前先 `DROP SCHEMA public CASCADE; CREATE SCHEMA public;`。
- EOL：新建 `app/`、`tests/` 文件须转 **CRLF**；`docs/**` 保持 LF。
- 🚨 **绝不在本仓库执行 `git rm`**（删单文件会把整个 `apps/backend/app/` 365 文件删光）；删文件用 `find <file> -delete`。
- 🚨 `git commit` 后**必须复核 `git rev-parse HEAD`**（本机曾出现分支 ref 不更新）。

### 0.5 前提五：客户端侧的「零复用」纪律

**不复用** `apps/frontend/`（React 调试控制台）。它是内部调试工具，语义与产品不同；强行复用会把 debug 语义带进产品。Flutter 侧独立建 `apps/mobile/`。

### 0.6 前提六：客户端选型已冻结（2026-09-23 确认）

技术栈已定：**Flutter + Riverpod + GoRouter + Dio + Freezed + Drift(SQLite) + Flutter Hooks + Material 3**（另补 10 项依赖）。完整评估、约束与成本分析见 `flutter-architecture.md` §1。

三条**必须遵守**的约束（违反即视为实现缺陷）：

| # | 约束 | 要点 |
|---|---|---|
| 1 | **Material 3 当底座不当皮肤** | 五条禁令：不用 `ColorScheme.fromSeed`、不用 M3 默认 `TextTheme`、显式关闭 `surfaceTintColor` 与默认 elevation、图标用 Lucide 不用 Material Icons、Tab 栏自绘 |
| 2 | **Flutter Hooks 只承载 widget 级临时资源** | 允许 `useAnimationController` / `useTextEditingController` / `useDebounce` / `useMemoized`；**禁止** `useState` 存业务状态、`useEffect` 拉数据、与 `StatefulWidget` 混用 |
| 3 | **Freezed 主用途是流式事件 union** | 给 `ChatEvent`（turn_meta / token / tool_step / done / failure）建 sealed union 以获得编译期穷尽检查；**普通 DTO 不必都上 Freezed**（Dart 3 原生 `final class` + 手写 `copyWith` 即可） |

⚠️ **构建成本提示**：`freezed` + `drift` + `riverpod_generator` 三生成器共用 build_runner。APP-001 必须完成输出后缀隔离（`build.yaml`），并约定「一个文件只被一个生成器处理」，否则 `.g.dart` 会互相覆盖。

### 0.7 前提七：11 条决策已全部拍定（2026-09-23）

`requirements-analysis.md` §6 已锁定 D0~D11，**不存在待拍板项**。与任务直接相关的 5 条强约束：

| 决策 | 结论 | 对任务的影响 |
|---|---|---|
| **D1** | 健康段**门控**：先做 `PLT-001` 实机验证再定排期 | **M4 全部任务 + `APP-023` 不得先于 `PLT-001` 开工**；`APP-014` 必须同时实现三宫格**空态 + 引导授权**分支 |
| **D5** | 记忆只展示 active 且未 forgotten；上限与衰减不向用户暴露 | `API-007` `APP-017` 口径 |
| **D6** | 新建轻量任务域（`life_tasks`，原迁移 `0055`，已并入基线 `0001`），不复用 plan step | `API-005` |
| **D9** | 设计 token 以 §06 色卡 + 原型为准 | `APP-002` 必须先拿到定稿色值再开工 |
| **D11** | **跳过 Figma 重建**：设计依据 = 设计稿 §06 + 原型 HTML | 不产生 Figma 相关任务；token 在 `APP-002` 一次性定稿 |

---

## 1. 任务总览

| 里程碑 | 主题 | 任务 | 数量 |
|---|---|---|---|
| **M0** | 地基：工程骨架 + 设计系统 + AI 核心球 | `APP-001 ~ APP-008` | 8 |
| **M1** | 对话闭环：身份 → 流式 → 过程卡 | `API-001~003` + `APP-009~012` | 7 |
| **M2** | 生活域与首页：聚合 → 记账 → 记忆 | `API-004~007` + `APP-013~017` | 9 |
| **M3** | 主动与我的：简报 → 通知 → 隐私 | `API-008` + `APP-018~022` | 6 |
| **M4** | 健康：接入 → 展示 → 授权 | `API-009~010` + `APP-023~025` | 5 |
| **PLT** | 平台横切：验证 / 合规 / 可观测 / CI | `PLT-001 ~ PLT-006` | 6 |
| | | **合计** | **41** |

---

## 2. M0 · 地基（`APP-001 ~ APP-008`）

> **目标**：交付一个「能跑起来、有设计系统、能渲染 AI 核心球」的空壳 App，后续所有页面都在它上面长。**M0 不依赖任何后端改动**，可立即开工。

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| APP-001 | Flutter 工程骨架与分层约定 | 基建 | P0 | — | `apps/mobile/` 工程、flavor（dev/prod）、目录分层、lint 规则、`analysis_options.yaml`；**`build.yaml` 三生成器隔离配置**（freezed / drift / riverpod_generator 输出后缀分离）、`build_runner watch` 约定、生成物纳入 CI 校验 |
| APP-002 | 设计 token 层（`ThemeExtension`）+ **M3 覆盖层** | 设计系统 | P0 | APP-001 | 色彩 10 项（含 AI 渐变 3 节点）、圆角 4 档、字号 6 级、投影 2 档、间距标尺；**禁止散落硬编码**；`app/theme/` 作为显式覆盖层逐项关掉 M3 默认值（禁 `fromSeed`、禁默认 `TextTheme`、关 `surfaceTint` 与默认 elevation）；**必须支持深色模式对调**（暖纸白 ↔ 深夜紫，故 `AppColors` 须为 `ThemeExtension` 而非 `static const`） |
| APP-003 | 网络层与 NDJSON 流式解析 | 基建 | P0 | APP-001 | dio 客户端、拦截器（令牌 / 错误映射 / 日志脱敏）、`LineSplitter` 流解析、统一错误模型；**Freezed `sealed class ChatEvent` 建模异构事件**（turn_meta / token / tool_step / done / failure），靠 `switch` 穷尽检查兜住后端新增事件类型 |
| APP-004 | 本地存储与凭据层 | 基建 | P0 | APP-001 | `flutter_secure_storage`（令牌）、drift（读缓存）、偏好存储（主动关怀开关等） |
| APP-005 | 导航骨架与深链 | 基建 | P0 | APP-001 | go_router 声明式路由、5 Tab（首页/**动态（默认记账，生活页长按模块卡可改设）**/对话悬浮球/生活/我的）、深链映射原型 9 页　**〔2026-10-03 IA 修订〕** |
| APP-006 | **AI 核心球（Orb）** | 核心组件 | P0 | APP-002 | 四态（待机/思考/主动/完成）× 四尺寸（76/56/34/22）；`CustomPainter` + `saveLayer(BlendMode.screen)`；`RepaintBoundary` + `TickerMode` 控功耗；**两个 `AnimationController` 用 `useAnimationController`（hooks 的合规用法）** |
| APP-007 | 基础组件库 | 设计系统 | P0 | APP-002 | 卡片、**渐变描边卡**（`CustomPainter`）、chip、开关、任务行、指标迷你卡（含 sparkline）、进度条、账单行、记忆卡、设置行 |
| APP-008 | 全局状态规范 | 设计系统 | P0 | APP-007 | 加载 / 空态 / 错误 / 骨架屏四态组件；错误文案规范（不暴露技术细节） |

**M0 验收口径**：一个可运行 App，能通过底部 Tab 切换 5 个空页；Orb 四态可在调试面板手动切换；设计 token 全部经 `ThemeExtension` 取用（**全仓 grep 无硬编码色值**）；与设计稿截图比对**无 M3 默认视觉特征**（无色渗、无 pill indicator、字号阶一致）。

---

## 3. M1 · 对话闭环（`API-001~003` + `APP-009~012`）

> **目标**：跑通「说一句话 → 看到 AI 逐字回复 → 看到 AI 做事的过程」。**M1 的收口点是 Tool Call 过程卡**，它依赖 API-002。

### 3.1 后端补齐

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 | 验收口径 |
|---|---|---|---|---|---|---|
| API-001 | **身份与设备绑定鉴权** | 安全 | P0 | — | 设备配对换长期令牌；服务端新增鉴权依赖，`user_id` 由 token 解析而非请求参数 | ① 无令牌请求 401；② 令牌只解出本人 `user_id`；③ 既有 `default_user` 行为零变更（基线对照法）；④ 纯新增，不动既有域 |
| API-002 | **对话流新增工具步骤事件** | 事件契约 | P0 | API-001 | `tool_step` 事件：`{step_id, tool_id, label, status: running\|done\|failed, detail, target}`，走**独立通道** | ① 新事件类型已登记 `EXPECTED_EVENT_TYPES`；② `loop_runs.steps` 键集**未变**（`test_agent_loop_core.py` 仍绿）；③ 记账链路能流式产出 4 步；④ 未知类型仍 fail-closed |
| API-003 | 记忆调用提示字段 | 契约扩展 | P0 | — | `turn_meta` 增本轮引用的记忆摘要（`memory_refs: [{id, kind, label}]`） | ① 无记忆引用时字段缺省（不返空数组，避免端上误判）；② 键集变更已登记 `V30_RUNTIME_FIELDS`；③ 零回归 |

> ⚠️ **API-002 的关键设计约束**：`test_agent_loop_core.py` 断言 loop 与 legacy 的 `loop_runs.steps` **键集完全相同**，因此工具步骤**不得**塞进 `steps`。事件须从工具执行侧（`services/tool/` 五段执行）经独立通道上报至 `chat.py` 的流。

### 3.2 客户端

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| APP-009 | 对话页装配 + 会话历史 | 页面 | P0 | APP-005, APP-007, API-003 | 会话列表、历史回放（`/conversations/{id}/messages`）、滚动定位；**长期记忆调用提示条**（「本轮已调用 3 条长期记忆：旅行偏好 · 预算习惯 · 作息」，数据来自 `API-003`） |
| APP-010 | **流式渲染引擎** | 核心 | P0 | APP-003 | token 增量渲染、Markdown 渲染、节流（避免逐字抖动）、长文本虚拟化、断流恢复 |
| APP-011 | 消息组件与输入栏 | 页面 | P0 | APP-007, APP-010 | 用户深色泡 / AI 白卡泡 + 迷你 Orb 头像、typing 指示器、输入栏（+ / 语音 / 发送，语音 P2） |
| APP-012 | 人格状态栏与 Role Mode 切换 | 页面 | P0 | APP-006, APP-009 | 顶部迷你 Orb + 名字 + 在线态 + 模式 chip；三档切换（professional / default / immersive） |

**M1 验收口径**：真机对着后端发一句话，能逐字看到回复；说「午饭 35 元」能看到 4 步过程卡逐项打勾且末步标注「已同步到生活 · 记账」；切到 professional 模式后 `turn_meta.role_mode` 变化且回复风格可见差异。

---

## 4. M2 · 生活域与首页（`API-004~007` + `APP-013~017`）

> **目标**：把「AI 今天已经帮我整理好了」这句话变成真的。**M2 是任务量最大的一段**，其中 API-004（首页聚合）是首页能否成立的前提。

### 4.1 后端补齐

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 | 验收口径 |
|---|---|---|---|---|---|---|
| API-004 | **首页聚合接口** | 聚合 | P0 | API-005, API-006, API-007 | `GET /home/summary`：问候 / Orb 状态语 / 模式 / AI 总结 / 健康三宫格 / 今日任务（含 `order_reason`）/ 今日消费 / 主动待办 | ① 单请求返回全部区块；② 跨域合成在服务端；③ 零 `repositories` 依赖；④ 任一子域不可用时不整体 500（区块级降级） |
| API-005 | 任务域（`life_tasks`） | 新领域 | P0 | — | 建表已并入基线迁移 `0001`（原编号 `0055_life_tasks.py`）；CRUD + 勾选完成 + 时间提醒注册 + 排序理由 | ① 迁移钉测已升级；② `SCHEMA_TABLE_COUNT` 同步；③ `create_check_constraint` 传完整布尔式；④ 零回归 |
| API-006 | **产品级洞察（Insight）读接口** | 新接口 | P0 | — | `GET /insights?domain=ledger\|health\|home&limit=N` → `{id, domain, headline, narrative, evidence[], source_refs[], generated_at}` | ① 零 `repositories` 依赖；② 无洞察时返空列表（不返 500）；③ 「AI 叙事优先」原则有真实数据源 |
| API-007 | 产品级记忆接口 | 新接口 | P0 | — | `GET /memory/items`（含 `source_kind` / `source_count` / `last_updated` / `usage_receipts[]`）+ 编辑 + 遗忘（置 `forgotten`） | ① 零 `repositories` 依赖；② 列表只含 active 且未 forgotten；③ 遗忘可审计；④ 用途回执有真实来源 |

> ⚠️ **API-005 与 API-006 需先完成 §6 决策 D5 / D6 的裁决**，否则实现口径会返工。

### 4.2 客户端

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| APP-013 | **Tool Call 过程卡与结果卡** | 核心组件 | P0 | API-002, APP-007 | 步骤四态渲染（done ✓ / running ◌ / todo ○ / failed ✗）、结果落点明示、结果卡 + 快捷操作 chips |
| APP-014 | **首页装配** | 页面 | P0 | API-004, APP-006, APP-013 | 问候 → Orb 英雄区 → AI 总结卡（渐变描边，视觉焦点）→ 状态三宫格 → 今日任务 → 今日消费 → 输入丸；**信息流严格「先结论、后数据、再行动」**；⚠️ **三宫格必须实现双分支**：`PLT-001` 通过走真实数据，未通过走**空态 + 引导授权**（不得留白、不得用假数据） |
| APP-015 | 生活页 | 页面 | P0 | APP-007, API-005 | 3 列 6 格模块宫格（含每模块 AI 摘要）+ 长按拖动重排（第一格即动态位）；**〔2026-10-03 IA 修订〕**捕获条与「即将上线」虚线占位已移除 |
| APP-016 | 记账页 | 页面 | P0 | APP-007 | 深色月度总览卡（含环比徽章）、「亚丝娜的观察」卡、分类支出条、最近账单（含记录方式标签）、订正交互 |
| APP-017 | 记忆页 | 页面 | P0 | API-007, APP-007 | 分组（长期偏好/习惯/目标/当下）、来源追溯、用途回执、编辑 / 遗忘、隐私承诺卡 |

**M2 验收口径**：冷启动进首页，**一次请求**拿到全部区块且 AI 总结卡是首屏最大视觉焦点；记账页数字与 `/ledger/summary` 完全一致；记忆页每条都能看到来源与用途回执，且「遗忘」后刷新不再出现。

---

## 5. M3 · 主动与我的（`API-008` + `APP-018~022`）

> **目标**：让「主动但克制」成立——固定节奏、可关闭、不打扰。

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 | 验收口径 |
|---|---|---|---|---|---|---|
| API-008 | 主动简报预生成与偏好存储 | 后端 | P0 | API-004, API-006 | 按用户设定时刻预生成**早间简报与晚间总结**两种内容；偏好读写（时刻、开关）；晚间总结须体现「未完成任务由 AI 重新排期而非催促」 | ① 偏好落库（非开关形态，按 V4.0.0 裁决 9）；② 简报内容可离线取到（供本地通知）；③ 两种简报共用一套渲染契约 |
| APP-018 | 简报页（早间 / 晚间两种形态） | 页面 | P0 | API-008, APP-006 | 深色全屏页（渐变背景）、四张卡（天气 / 日程 / 任务 / 生活节奏）、早间以「开始今天」收尾、晚间以「安顿明天」收尾 | 深链可达；两种形态共用布局、按类型切换文案与卡片；返回首页状态栏颜色正确还原 |
| APP-019 | 本地通知调度 | 端侧 | P0 | APP-004, API-008 | `flutter_local_notifications`；按设定时刻本地触发；点击落地到简报页 | ① 关闭开关后不再触发；② 系统权限被拒时有引导；③ 时区 / 重启后调度仍有效 |
| APP-020 | 我的页 | 页面 | P0 | APP-006, API-001 | 用户卡（相识天数 · 关系等级）、AI 人格卡（深色 + Mode 三段）、设备 / 授权 / 记忆 / 隐私设置组、主动关怀三开关 | 关系等级数据来自产品级接口（非 debug） |
| APP-021 | **隐私与授权页** | 合规 | P0 | APP-004 | 数据授权范围管理、单独同意（健康数据）、导出（`/life/export`）、一键清空（`/life/data`） | ① 健康授权独立勾选；② 清空有二次确认；③ 文案按决策 D2 裁决落地 |
| APP-022 | 快速捕获意图路由 | 功能 | P1 | API-005, API-007 | 一句话 → AI 判断归到**记账 / 任务**，并回执「已归到 XX」；⚠️ **V1 降级裁决：不建独立备忘录域**，备忘录类输入统一落任务域（带 `kind=memo` 标记），独立备忘录域列 V2 | 归错时可一键改归；不猜（低置信走澄清）；降级后「生活 · 备忘录」模块卡显示任务域内的 memo 计数 |

**M3 验收口径**：设定 08:00 后真机在设定时刻收到本地通知，点击进入简报页；关掉开关后不再收到；隐私页能成功导出与清空。

---

## 6. M4 · 健康（`API-009~010` + `APP-023~025`）

> 🚦 **整段为门控段（决策 D1）**：**`PLT-001` 实机验证未出结论前，本段任何任务不得开工**，`APP-023` 亦不得先于 `PLT-001` 启动。
> - 验证**通过** → 健康事实域 + 只读展示进 V1；异常主动提醒（`REQ-PROA-04`）仍留 V2。
> - 验证**未通过** → 本段整体后置；`APP-014` 的三宫格走**空态 + 引导授权**分支（该分支属 M2 范围，不因本段后置而缺席）。

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 | 验收口径 |
|---|---|---|---|---|---|---|
| API-009 | 健康数据 ingest 与存储 | 新领域 | P1 | PLT-001 | 新增增量迁移 `0003+`（原规划 `0056_health_facts.py`）；`health_*` 三件套；ingest 工具 `builtin.health.sync` | ① **健康数据不进 memory 域**（同 V4.0.0 裁决 2 纪律）；② 命名避开既有 `services/tool/health.py`（工具熔断健康度）；③ 幂等 ingest |
| API-010 | 健康评分与洞察 | 后端 | P1 | API-009, API-006 | 「综合 N 分」评分口径、睡眠趋势批注、异常趋势检测 | ① 评分口径文档化（不可黑箱）；② 文案禁医疗级宣称 |
| APP-023 | 健康数据接入 | 端侧 | P1 | APP-021 | Health Connect（Android）/ HealthKit（iOS）细粒度读权限申请与同步 | ① Android 14+ 处理 `VIEW_PERMISSION_USAGE` + `HEALTH_PERMISSIONS`；② 权限被拒可降级 |
| APP-024 | 健康页 | 页面 | P1 | APP-023, API-010 | 状态 Hero 卡（Orb + 综合分 + 叙事）、睡眠 7 日趋势 + AI 批注、今日指标行（每项附 AI 建议）、数据来源声明 | 首屏是结论不是数据 |
| APP-025 | 健康授权与免责 | 合规 | **P0** | APP-021 | 独立同意流程、隐私政策 rationale、「非医疗建议，请咨询医生」常驻 | **无论健康模块是否上线，只要有健康文案就必须交付** |

**M4 验收口径**：真机授权后首页三宫格显示真实数据且标注来源；健康页首屏是「今天状态不错」而非指标表；任意健康页均可见免责声明。

---

## 7. PLT · 平台横切（`PLT-001 ~ PLT-006`）

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 | 验收口径 |
|---|---|---|---|---|---|---|
| **PLT-001** | **Phase 0 手环实机验证** | 前置验证 | **P0** | — | 验证 Mi Fitness 国内版是否原生写入系统健康平台、可同步字段与延迟 | 输出结论报告；**结论直接决定 M4 排期与首页三宫格形态** |
| PLT-002 | 合规与上架准备 | 合规 | P0 | APP-021 | 隐私政策、单独同意文案、中国 App 备案、商店资质调研（调研已列 4 项未闭合） | 4 项未闭合项各有结论（备案细则 / NMPA SaMD 分类 / Google Play 健康政策 / 国内安卓商店健康资质） |
| PLT-003 | 可观测与埋点 | 基建 | P1 | APP-001 | 崩溃上报、首屏耗时、对话成功率、关键漏斗 | 日志**禁打**账目金额与健康数值 |
| PLT-004 | 测试策略 | 测试 | P0 | APP-001 | widget test + golden test（Orb / 卡片视觉回归）+ mock server（对齐现有前端 msw 思路）；**五条设计原则验收化**（把「AI 叙事优先 / 卡片即结论 / 记忆可见 / 主动但克制 / 温暖而非企业」转成 5 条可判定的 golden 与人工走查规则） | golden 覆盖 Orb 四态 + 关键卡片；**另加 M3 特征回归**（不得出现色渗 / pill indicator / 默认字号阶）；**codegen 产物校验**（`build_runner build` 后 `git diff --exit-code`）；CI 可跑 |
| PLT-005 | CI/CD 与发布流水线 | 基建 | P1 | APP-001 | 构建 / 签名 / 内测分发（Android 内测渠道 + TestFlight） | flavor 隔离正确；密钥不进仓库 |
| PLT-006 | 性能基线与优化 | 性能 | P1 | APP-014 | 冷启动首屏 ≤ 2.5s、首 token ≤ 1.5s、列表 60fps、Orb 功耗 | 有可复现的测量方法，非主观判断 |

---

## 8. 关键路径与依赖图

```text
PLT-001（手环验证）────────────────────────────┐
                                               ↓
APP-001 → APP-002 → APP-006 ┐            M4 健康段（APP-023~025 / API-009~010）
        ↓                    │
      APP-003 → APP-010 ─────┤
        ↓                    ↓
      APP-007 → APP-013 ──→ APP-014（首页）
        ↓                    ↑
      APP-005 ───────────────┤
                             │
API-001（鉴权）→ API-002（工具事件）┘
                    ↓
                 APP-013（过程卡）

API-005 → API-004（首页聚合）← API-006 / API-007
```

**关键路径（最长链，决定总工期）**：

```text
APP-001 → APP-002 → APP-007 → APP-013 → APP-014
                    ↑
API-001 → API-002 ──┘
```

**四个关键收口点**：

| 收口点 | 判定标准 |
|---|---|
| **C1**（M0 末） | 设计系统冻结：token 全部经 `ThemeExtension`，Orb 四态可切，全仓无硬编码色值 |
| **C2**（M1 末） | 工具事件打通：`tool_step` 流式产出且 `loop_runs.steps` 键集未变 |
| **C3**（M2 末） | 首页单请求成型 + 记账页与后端数字逐项一致 |
| **C4**（M3 末） | 主动节奏成立：本地通知准时、可关、不重复 |

---

## 9. 风险登记

| # | 风险 | 概率 | 影响 | 触发信号 | 应对 |
|---|---|---|---|---|---|
| R1 | **Mi Fitness 国内版不写系统健康平台** | 中 | 高（M4 整体不可行） | PLT-001 验证失败 | 降级：手动导入 / 引导用户装 Gadgetbridge / 健康模块后置 |
| R2 | **工具事件改动打破 `loop_runs.steps` 键集钉测** | 中 | 高（阻塞 C2） | `test_agent_loop_core.py` 转红 | 事件走独立通道（API-002 已明确约束）；先 `git worktree` 测 blast radius |
| R3 | **加迁移打破约 22 个跨版本钉测** | 高 | 中 | 钉测批量转红 | 预留专门一轮升级钉测机制（同 V4.0.0 PLA-001 的做法） |
| R4 | **健康 / 任务域裁决未定导致返工** | 中 | 中 | D1 / D5 / D6 迟迟不决 | 把 API-005 / API-006 的 Detail 与决策绑定，决策不落地不开工 |
| R5 | **Flutter 端渲染性能不达标**（流式 + Markdown + Orb 动画并存） | 中 | 中 | 首 token 延迟 / 掉帧 | APP-010 节流 + 虚拟化；APP-006 用 `RepaintBoundary` + `TickerMode` 隔离 |
| R6 | **隐私文案与存储架构不一致引发审核问题** | 中 | 高（合规） | 商店审核被拒 | D2 决策后统一改文案；PLT-002 与 APP-021 绑定 |
| R7 | **单用户鉴权改造影响既有域** | 低 | 高 | 基线对照出现新失败 | API-001 严格「纯新增」；零回归用基线对照法验证 |
| R8 | **`git rm` / 批量删除触发仓库级事故** | 低 | 极高 | 删除操作后 `git status` 出现大量删除 | 严格执行 §0.4：删文件一律 `find <file> -delete` |

---

## 10. 与仓库铁律的对齐检查表（每个 Task Detail 生成前逐项过）

- [ ] 新 API 是否**零** `app/repositories` 依赖？
- [ ] 新增设置项是否为**参数类**（非 `*_enabled` 功能位）？env 名是否 = 字段名大写？
- [ ] 新增事件类型是否已登记 `EXPECTED_EVENT_TYPES`？
- [ ] 是否触碰 `loop_runs.steps` 键集？（**禁止**）
- [ ] 是否新增迁移？若是：`create_check_constraint` 传的是完整布尔式吗？钉测升级了吗？`SCHEMA_TABLE_COUNT` 同步了吗？
- [ ] 是否改动 `world_*` / `memories` / `relationship_state` / `loop_runs`？（**禁止直写**）
- [ ] `services` 是否 import 了 `app.application`？（**禁止**）
- [ ] 新增 `runtime_*` 字段是否登记 `V30_RUNTIME_FIELDS`？
- [ ] 零回归是否用**基线对照法**验证（而非期待全绿）？
- [ ] 新建 `app/` / `tests/` 文件是否转了 CRLF？
- [ ] 是否误用 `git rm`？（**禁止**）提交后是否复核了 `git rev-parse HEAD`？

---

## 11. Task Detail 索引与生成记录（2026-09-23）

> **状态**：41 个 Task Detail **已全部生成**，位于 `docs/version/v5.0.0/tasks/`；统一体例见 `tasks/README.md`（10 章体例 + 三条任务线差异化要求 + 全局约束速查）。
> **总量**：41 个明细 / 约 17.5 千行 / 单文件 378–450 行。

### 11.1 索引

| 里程碑 | 任务线 | 明细文件 |
|---|---|---|
| **M0** 地基 | `APP-001`~`APP-008` | `tasks/APP-001.md` ~ `tasks/APP-008.md` |
| **M1** 对话闭环 | `API-001`~`API-003` | `tasks/API-001.md` ~ `tasks/API-003.md` |
| **M1** 对话闭环 | `APP-009`~`APP-012` | `tasks/APP-009.md` ~ `tasks/APP-012.md` |
| **M2** 生活域与首页 | `API-004`~`API-007` | `tasks/API-004.md` ~ `tasks/API-007.md` |
| **M2** 生活域与首页 | `APP-013`~`APP-017` | `tasks/APP-013.md` ~ `tasks/APP-017.md` |
| **M3** 主动与我的 | `API-008` | `tasks/API-008.md` |
| **M3** 主动与我的 | `APP-018`~`APP-022` | `tasks/APP-018.md` ~ `tasks/APP-022.md` |
| **M4** 健康（门控） | `API-009`~`API-010` | `tasks/API-009.md` ~ `tasks/API-010.md` |
| **M4** 健康（门控） | `APP-023`~`APP-025` | `tasks/APP-023.md` ~ `tasks/APP-025.md` |
| **PLT** 平台横切 | `PLT-001`~`PLT-006` | `tasks/PLT-001.md` ~ `tasks/PLT-006.md` |

> **V5.1 增量明细已生成（2026-09-30）**：`PLT-007` / `API-015~020` / `APP-027~043` 共 **24 个 Task Detail 已全部生成**（10 章体例，与 41 个既有明细同规范），索引如下；注册表见 **§15**，生成记录与偏离声明见 **§15.9** / **§15.12**。

| 期 | 任务线 | 明细文件 |
|---|---|---|
| 一期 记账扩展 | `API-015`~`API-017` | `tasks/API-015.md` ~ `tasks/API-017.md` |
| 一期 记账扩展 | `APP-027`~`APP-029` `APP-041` | `tasks/APP-027.md` ~ `tasks/APP-029.md`、`tasks/APP-041.md` |
| 二期 车辆域 | `API-018`~`API-020` | `tasks/API-018.md` ~ `tasks/API-020.md` |
| 二期 车辆域 | `APP-030`~`APP-033` `APP-042` | `tasks/APP-030.md` ~ `tasks/APP-033.md`、`tasks/APP-042.md` |
| 三期 相册域 | `PLT-007` | `tasks/PLT-007.md` |
| 三期 相册域 | `APP-034`~`APP-040` `APP-043` | `tasks/APP-034.md` ~ `tasks/APP-040.md`、`tasks/APP-043.md` |

**每个明细文件的结构**：`1. Task Overview`（含 `完成判据` 与 `新增设置`）/ `2. Background`（现状证据带 `文件:行号`）/ `3. Scope`（In / Out，Out 是反范围护栏）/ `4. Technical Design Requirements`（4.1 契约 · 4.2 关键裁决 · 4.3 数据流 · 4.4 依赖与边界）/ `5. Implementation Plan` / `6. File Impact`（含 6.3 禁止修改红线）/ `7. Testing Requirements`（用例名 + 断言）/ `8. Acceptance Criteria`（AC# + 判据 + 验证方式）/ `9. Commit Requirement` / `10. 需求溯源`（设计稿条目 → REQ → 覆盖状态，带 `traceability.md` 行号）。

### 11.2 生成过程中发现的 5 个跨任务缺口（**需回写，不是本次撰写能自行了结的**）

| # | 缺口 | 证据 | 影响 | **处置（2026-09-24 回写）** |
|---|---|---|---|---|
| **N1** | **`API-008` 的「按设定时刻预生成」需要第 3 个迁移** | `tasks/API-008.md` §4.2 | 简报离线预取 | **已按零迁移处置**：`GET /brief/{form}` 按设定时刻即时生成（复用 `task_service` 读面），未建第三迁移；本地通知落地页可拉最新简报。若后续必须离线预生成，再开迁移并改 §0.3 |
| **N2** | **关系等级无产品级接口** | 仅 `/debug/relationship/*` | `APP-020` 用户卡 | **已降级处置**：`APP-020` 用户卡展示「相识天数 · 关系 Lv.」占位文案，不调 debug 接口；关系读接口列 **V5.1** |
| **N3** | **Role Mode 切档无写路径** | 无 mode 端点 | M1 验收不可达 | **已闭合**：新增 `POST /state/mode`（`conversation_service.set_preferred_mode` → `update_mode`），写最近会话 confirmed mode |
| **N4** | **`APP-013` failed 态视觉未设计 sign-off** | `components.md` A14 仅三态 | 视觉基线 | **实现已带 failed 态**（暖橙叉 + 文案）；**待设计 sign-off** 后回写 `components.md` A14 |
| **N5** | **记忆页 H1 口径张力** | D5 vs 设计系统 B7 | 两套真源 | **已按设计系统执行**：H1=「亚丝娜记住的你」，D5 措辞不进 H1；若 D5 为准须先改 skill |

### 11.3 待确认项（不阻塞撰写，但影响开工）

| # | 事项 | 相关任务 | **处置（2026-09-24 回写）** |
|---|---|---|---|
| Q1 | 字重方案 | `APP-002` | **已定：降级映射** `550→w500 / 650→w600 / 750→w700` |
| Q2 | `EXPECTED_EVENT_TYPES` 与 NDJSON 集合 | `API-002` | **已定：同批登记** `ToolStepRecorded`；wire 形态 `tool_step` |
| Q3 | 令牌签名密钥来源 | `API-001` | **已定：新增参数类 `auth_token_secret`**（env=`AUTH_TOKEN_SECRET`，见 `.env.example`） |
| Q4 | 健康域命名避歧 | `API-009` | 暂定 vitals；M4 开工时再定 |
| Q5 | 晚间简报第 4 张卡 | `API-008` | **已定：`remembered`「记住的你」** |
| Q6 | golden CI 一致性 | `PLT-004/005` | 暂定本地生成入库；CI 只校验 diff |
| Q7 | PLT 落点 | `PLT-001/002` | **已定**：`compliance/plt002-notes.md`、`perf/plt006-baseline.md` |
| Q8 | CI 载体 | `PLT-005` | **已定：GitHub Actions**（`.github/workflows/ci.yml`） |
| Q9 | 授权范围持久化 | `APP-021` | 暂用端侧偏好 |
| Q10 | Orb 功耗阈值 | `PLT-006` | 先基线后定目标（`perf/plt006-baseline.md`） |

### 11.4 明细对注册表的**零偏离声明**

41 个明细的 `In Scope` 全部落在本注册表 §2~§7 的「交付面」范围内，`Out of Scope` 逐条对应 §7.3 反范围清单与 §0 七条前提。**唯一需要注册表回写的是 §11.2 的 5 个缺口**（N1~N5）——它们不是明细擅自扩张，而是撰写时按证据发现的上游遗漏，处置权在注册表与需求文档。

> **变更顺序纪律不变**（见 `traceability.md` §12）：需求变更先改覆盖矩阵 → 再改 `requirements-analysis.md` → 最后改本注册表与明细。**顺序不可颠倒。**

---

## 12. 增量注册：邮箱验证码登录（2026-09-27，已实现）

> **背景**：真机验收留下的「邮箱登录无令牌」深层缺口（原验证码页为本地假登录，任意 6 位放行、不调后端）。本节为**实现后补记**的增量注册（体例从简，不另立 41 任务式 Detail），设计裁决见 `docs/current-system-architecture-baseline.md` §8.4 / §10 ADR-12。
> **范围**：5 个任务（延续 API- / APP- 编号），迁移 `0057_users_email.py`（users.email 唯一部分索引；0056 为并行会话已入链的 life_tasks kind 白名单，非本节范围）。验证码状态**存 Redis 不建表**（GETDEL 单次消费），发件走 `EmailSender` 协议（MVP = SMTP 163 个人邮箱，换 Resend/阿里云/腾讯云只加实现类）。

| Task ID | 名称 | 交付面 | 状态 |
|---|---|---|---|
| `API-011` | Redis 基座接入 | `docker-compose.yml`（redis 服务 + healthcheck）· `pyproject` redis 依赖 · `redis_url` 设置 · `core/redis_client.py`（懒建单例 + lifespan ping/close） | 已实现 |
| `API-012` | 验证码存储协议 + Redis 实现 | `services/identity/code_store.py`（`VerificationCodeStore` 协议 + `RedisCodeStore`：SETNX 冷却 / INCR+EXPIRE 频控 / GETDEL 消费 / 尝试超限作废）+ `tests/unit/test_code_store.py`（fakeredis） | 已实现 |
| `API-013` | 邮件发件端口 | `core/settings/email.py`（`EMAIL_*` 域）· `services/email/sender.py`（`EmailSender` 协议 + `SmtpEmailSender` 163：465 SSL + 授权码）+ `tests/unit/test_email_sender.py` | 已实现 |
| `API-014` | 验证码服务 + 登录端点 + 迁移 | `services/identity/verification.py`（签发/校验/策略）· `services/identity/user_service.py`（find-or-create by email，display_name=邮箱前缀）· `api/v1/auth.py`（`POST /auth/email/code` 429+Retry-After、`POST /auth/email/verify` 契约同 `/auth/pair`，缺 SMTP/Redis/密钥 503）· 迁移 0057 + `tests/v50/test_email_login.py` | 已实现 |
| `APP-026` | 客户端接线 | `auth_repository.dart`（`requestEmailCode` / `verifyEmailCode` / `AuthCodeException` 状态码+Retry-After 透传）· `verify_code_page.dart`（进页即发码、重发接冷却、验证通过换令牌写 SecureTokenStore 后进首页，假登录语义移除）+ `login_flow_test.dart`（12 用例） | 已实现 |

**测试门槛（已过）**：后端 `tests/v50` + 三个新 unit 文件 64 绿；迁移 0057 up/down 往返在真实 PG 验证；钉测中心 `tests/support/schema_pins.py` 已修至 `0057`（并修正 0056 遗漏的钉测失修）；移动端全量 117 绿。

**回归清单（真实模型 / 真机人工项）**：

1. `docker compose up` 后 `redis-cli ping` 通、后端启动日志出现「Redis 连接正常」。
2. 配置 `EMAIL_SMTP_*`（163 授权码）后：App 登录页输入邮箱 → 收到验证码邮件（查垃圾箱）→ 输码 → 进首页；`users` 表出现 `email-*` 用户行。
3. 60s 内重发 → 429 提示剩余秒数；连错 5 次 → 提示作废需重取；过期码（>5min）→ 提示过期。
4. 登录成功后杀 App 重开 → 免登录直达；`/profile` 登出 → 回登录页。
5. 配对码链路回归：`POST /auth/pair` 行为不变（两套认证并存）。

---

## 13. 增量注册：设备配对链路退役（2026-09-27，已实现）

> **背景**：邮箱验证码登录（§12）落地后，配对码（API-001）失去独立价值：签发面只有 `default-user` 无身份语义、静态共享密钥不可撤销，且 owner 侧无历史数据继承诉求。裁决整体退役，邮箱验证码登录成为唯一登录入口。
> **契约不变量**：令牌格式（`user_id.device_id.exp.hmac`）、`/auth/me`、`require_user` 依赖、端侧 SecureTokenStore 存储链路均不变，仅令牌签发入口由配对码换为邮箱验证码。

| 变更 | 内容 |
|---|---|
| 后端 | 删 `POST /auth/pair`、`auth_pairing_code` 设置、`PairRequest`；`PairResponse` → `TokenResponse`；`tests/v50/test_auth_token.py` 移除配对用例（`AUTH_TOKEN_SECRET` 保留，令牌签名仍需） |
| 移动端 | 删 `pairing_page.dart`、`/profile/pairing` 路由与 chrome 元、个人页「设备配对」入口；`AuthRepository.pair()` 删除、`PairResult` → `TokenResult`；登出文案去「或配对」 |
| 配置 | `.env.example` 删 `AUTH_PAIRING_CODE`；部署侧 `.env` 同步删除该键（env 同步纪律） |
| 测试门槛 | 后端 Fast 1950 绿（仅 §12 已登记的 2 处遗留红，非本次）+ pylint 8.97；移动端全量 117 绿 |
| 影响 | SMTP / Redis 不可用期间无备用登录路径（可接受：自部署场景 owner 可直接改库签发/绑邮箱救急） |

---

## 14. 增量注册：用户身份收口（IDENT-001~008，2026-09-27）

> **背景**：邮箱验证码登录（§12）与配对退役（§13）落地后，token 身份只覆盖生活域 7 个产品端点（tasks/memory/insights/home/brief/health）；核心对话面 `/chat/message` 硬编码 `default-user`，`history` / `governance` / `ledger` / `proactive` 仍按请求参数回落 `default-user`。三套身份空间并存（`default-user` / `email-*` / `feishu:{open_id}`），登录用户与对话数据主体脱节：聊天落 default-user，生活域读 token 用户，首页任务/消费恒为空。
> **裁决**：
> - **D1 数据归属（归并而非搬迁）**：单人自部署，owner 真实数据全在 `default-user` 名下 → 一次性归并脚本 `scripts/adopt_owner_identity.py`：`email-*` 散数据并入 default-user → owner 邮箱绑定 default-user 行（`users.email` 唯一约束，0057）→ 删 email-* 行；登录命中 default-user 行，token `user_id` 即 `default-user`（不透明 id，后续零数据搬迁）。
> - **D2 测试策略**：`default-user` 保留为**测试身份**（settings 驱动）；conftest autouse `dependency_overrides[require_user]` 注入 default-user，存量 HTTP 测试零逐文件改动；鉴权语义（401 / 越权 403 / 冷启动）另立专项测试 `tests/v50/test_identity_cutover.py`。
> - **D3 调试面划界**：`/debug/*`（world / action / action_execution / debug）与 `/state` 保持「`user_id` 客户端直传 + default-user 回落」的调试台语义（IDENT-010 留白 P2）；**产品面 = 移动端实际调用集合**。
> - **兼容红线变化**：V4.0.0「user_id 缺失回落 default_user 与现状逐字节一致」裁决自本变更废止——产品端点无 token 一律 401；调试面不变。基线 ADR 13 已同步。

| ID | 变更 | 内容 | 状态 |
|---|---|---|---|
| IDENT-001 | 对话收口 | `/chat/message` 接 `require_user`，`chat.py` 删 `get_settings().default_user` 硬编码，token user_id 贯穿 `stream_chat` | 已实现 |
| IDENT-002 | 治理端点收口 | `/life/export`、`DELETE /life/data` 接 `require_user`，删 default-user 锁定与 `user_id` Query（原无鉴权可导出全量生活数据，安全修复） | 已实现 |
| IDENT-003 | 账本收口 | ledger 全端点接 `require_user`，删 `_current_user` 的 default-user 特判（原显式非 default 用户反被 403）；请求体「禁止客户端指定」`user_id` 字段删除，服务端注入 | 已实现 |
| IDENT-004 | 历史/主动收口 | `/conversations/latest`、`/conversations/{id}/messages`（补属主比对 404）、`/proactive/pending`、`/proactive/{id}/ack` 接 `require_user`（移动端在用面） | 已实现 |
| IDENT-005 | owner 归并脚本 | `scripts/adopt_owner_identity.py --email`：动态发现含 `user_id` 列的表 → email-* 数据并入 default-user → 绑定邮箱 → 删 email-* 行；幂等，`--dry-run`。**2026-09-28 已执行完毕，脚本随默认用户概念退役删除**（其目标 id 概念已不存在；接替者见 IDENT-009 的 `migrate_owner_id_to_email.py`） | 已实现（已退役） |
| IDENT-006 | 调试台适配 | Debug Console `http.ts`/`chat-stream.ts` 注入 `Authorization`（localStorage token）+ 顶栏「身份」对话框（贴 token → `/auth/me` 校验显示）；`use-active-user-id` 语义不变（调试台仍可显式指定 user_id） | 已实现 |
| IDENT-007 | 后台用户集合 | `digest.py` / `alert.py` `run_maintenance` 按 `user_repository.list_all` 迭代；空表回落 default-user 分支已于 IDENT-009 摘除（启动播种保证非空，分支不可达） | 已实现 |
| IDENT-008 | 冷启动回归 | 专项测试 `tests/v50/test_identity_cutover.py`：无 token 401；token 身份贯穿（聊天落库/历史隔离/账本 scope/导出 scope）；全新用户首轮对话不崩（世界/角色状态空态口径） | 已实现 |

留白：IDENT-010（调试面鉴权）、IDENT-011（feishu 身份与 email 身份并集）均 P2，另行登记。IDENT-009 已执行（见下）。

**IDENT-009 执行结论（2026-09-28，默认用户概念整体退役）**：不再存在"默认用户"这一身份概念——用户行一律由登录链路派生（邮箱 → `email-<sha256[:16]>`；通道 → `feishu:{open_id}`）。

| # | 退役项 | 落地 |
|---|---|---|
| 1 | `settings.default_user` 字段 + `DEFAULT_USER` env | 已删。保留可配置面本身是地雷：改它会让播种撞 `ux_users_is_default` 唯一索引而静默失败 |
| 2 | 启动播种 `ensure_default_user()` + `user_repository.upsert_default()` | 已删（`main.py` lifespan 不再播种）。空库冷启动不再造幽灵行，等首次登录自然建行 |
| 3 | 调试面回落值（`state.py` / `world.py`，共 20 个端点） | 改为**token 身份**：`user_id` 省略即取 `require_user`，显式传入可覆盖。`/state`、`/debug/*` 由无鉴权变为需 token（提前兑现 IDENT-010 的语义） |
| 4 | `users.is_default` 列 + `ux_users_is_default` 唯一索引 + `UserContext.is_default` | 已删（迁移 `0058`）。该列此前是**纯装饰**——全仓无任何查询用它，只有写入端 |
| 5 | 一次性归并脚本 `scripts/adopt_owner_identity.py` + 测试 | 已删（目标概念消失；`adc57e4` 记录其已执行完毕） |
| 6 | `user_service.resolve_user()` 死代码 | 已删（生产零调用点） |

**接替工具**：`scripts/migrate_owner_id_to_email.py` —— 把历史 owner 行 id 由 `default-user` 改成邮箱派生 id，级联改写所有 `user_id` 列 + `worlds.id` + 所有 `world_id` 列（全部动态发现，幂等，默认 dry-run，`--apply` 单事务）。**待跑**：需部署侧 `alembic upgrade head`（0058）后执行；副作用是**所有已签发 token 失效**（无状态签名里带 user_id），需重新登录一次。

**测试身份**：`tests/conftest.py::TEST_USER_ID`（值取 `default-user`）。取值沿用历史字面量是刻意的——全仓约 300 处世界域夹具会派生 `home:default-user` 这类 world_id，整体改名属纯 churn，未纳入本次；语义上它只是夹具的任意 id，生产已无此概念。

**测试门槛（IDENT-009，2026-09-28）**：后端全量在**同条件**下双树对照（PG 已起、每次运行前 `DROP SCHEMA public CASCADE` 重置 `asuna_test`）——HEAD 干净 worktree 基线（`adc57e4`）**27 failed / 7154 passed / 2 skipped**，本变更 **27 failed / 7153 passed / 2 skipped**；25 条为两树共有（既有失败），差异仅 1 条/侧（`test_tool009_evidence::test_projection_failure_is_isolated_per_window` vs `test_debug_trace_persist::test_lru_evicted_turn_falls_back_to_db`），两者在各自树隔离重复 3 次均通过 → **零确定性回归**。

**PG 迁移已实测**：`tests/integration/test_db_migration.py::test_alembic_upgrade_matches_orm_metadata` 在 PG 上通过 → `alembic upgrade head`（含新 `0058`）产出的 schema 与 ORM metadata 逐列一致。

**数据迁移脚本已实测**：`tests/v50/test_migrate_owner_id.py` 6/6（内存 SQLite，覆盖 `user_id` / `worlds.id` / `world_id` 三条级联路径、dry-run 零写入、重复执行、无邮箱拒绝、目标已存在拒绝）。

**前端**：`tsc -b` 通过 + vitest 154/154。

注：本机 `.venv` 与 `uv.lock` 不同步（缺 `redis` / `fakeredis` / `aiosmtplib` / `sortedcontainers`），已 `uv sync --all-groups` 补齐；另本机 `asuna` 库停在 revision `0035`（无 `users` 表），直接跑 `migrate_owner_id_to_email` dry-run 会因缺表报错——属既有环境问题，非本变更。

**测试门槛（已过，2026-09-27）**：后端全量 7153 绿（28 失败经 HEAD 干净 worktree 基线对照逐项归因：22 既有红 + 4 本地 `.env` SMTP/Redis 环境敏感 + 1 tool007 冻结源钉测因前序会话未提交的 world_engine 改动 + 1 既有时序 flake，**本变更零确定性回归**）；`tests/v50` 鉴权专项 + 归并脚本 + 登录/令牌共 34 绿；前端 typecheck + 154 绿；移动端零改动。

**回归清单（真机 / 真实部署人工项）**：

1. 部署侧执行一次归并：`uv run python -m scripts.adopt_owner_identity --email <owner邮箱>`（dry-run 核对报告）→ `--apply`；确认 `users` 表 default-user 行 email 已绑定、`email-*` 行已删（或按 warning 保留）。—— **已执行（2026-09-28）**：email-* 散用户名下零数据，绑定 + 删行完成，登录解析验证 `find_or_create_by_email → default-user`，13 条记忆与会话数据完好。
2. App 登录（owner 邮箱）→ 发消息 → 杀 App 重开 → 会话历史恢复；`conversations` / `memories` / `character_state` 均在 default-user 名下。**注意：归并前拿到的旧 token 指向已删的 email-* 行（令牌无状态不校验库），须退出登录重登一次换新令牌**。
3. 首页任务 / 今日消费非空（聊天链路创建的任务与账目对 token 用户可见）——归并前创建的历史数据需第 1 步完成后新产生的对话验证口径。
4. 无 token 直接请求 `/api/v1/chat/message`、`/life/export`、`/ledger/summary`、`/conversations/latest` → 401；隐私页「导出数据」只含本人数据。

---

## 15. 增量注册：V5.1 设计稿新增模块（2026-09-30）

> **背景**：`design/pages/` 于 2026-09-30 新增 10 页（33 / 34 / 35 / 36 / 37 / 38 / 39 / 60 / 61 / 62）并改动 2 页（30 生活 / 31 账本）。三块能力的技术形态**完全不同**（记账扩展 = 接线补读面；车辆 = 新建域 + 迁移；相册 = 纯端侧原生能力），故按「**记账 → 车辆 → 相册**」三期交付，每期独立可验收。
> **上游（需求依据）**：`requirements-analysis.md` §2.4 / §3.5 / §4.10~§4.13 / §6.1（D12~D22）/ §7.1 —— 本注册表之外的任何能力不得开工。
> **上游（覆盖核对）**：`traceability.md` **§13**（V5.1 增量覆盖矩阵，12 页 × 5 行，44 ✅ / 12 ⚠️ / 4 🚫）。
> **上游（需求确定件）**：`reviews/v5.1-requirements-determination.md`（14 项冲突缺口 15~28 + 决策 D12~D22 + 反范围补充）。
> **体例**：沿用 §12~§14 的**增量注册体例**（从简，不另立 41 任务式 Detail）——见 **§15.9 关于 Task Detail 产出时机的决策 D22**。
> **主干**：**24 个任务** / 3 条任务线（`APP-027~043` 客户端、`API-015~020` 后端、`PLT-007` 平台横切）/ 3 期 + 1 个前置。
> **本文档不含代码、不含 DDL、不含 UI 稿。**

### 15.1 任务总览

| 期 | 主题 | 任务 | 数量 |
|---|---|---|---|
| **前置** | 工具链与依赖可行性（相册期硬门槛） | `PLT-007` | 1 |
| **一期** | 记账扩展：手动记账 / AI 自动记账 / 账本双入口 | `API-015~017` + `APP-027~029` `APP-041` | 7 |
| **二期** | 车辆域：车辆 / 养车记一笔 / 车辆档案 / 生活页车辆卡 | `API-018~020` + `APP-030~033` `APP-042` | 8 |
| **三期** | 相册域（仅本机）：相册 / 批量管理 / 相簿详情 / 单张照片 / AI 整理建议 / 生活页相册卡 | `APP-034~040` `APP-043` | 8 |
| | | **合计** | **24** |

### 15.2 新增路由（10 条子流程路由，全部复用 `chromeImmersive`）

| 路由 | 页面 | 设计稿 | 期 |
|---|---|---|---|
| `/ledger/add` | 手动记账 | 33 | 一 |
| `/ledger/auto` | AI 自动记账 | 34 | 一 |
| `/car` | 车辆 | 35 | 二 |
| `/car/add` | 养车记一笔 | 36 | 二 |
| `/car/profile` | 我的车（车辆档案） | 39 | 二 |
| `/album` | 相册 | 37 | 三 |
| `/album/manage` | 相册批量管理 | 38 | 三 |
| `/album/detail` | 相簿详情（带 `?album=`） | 60 | 三 |
| `/album/photo` | 单张照片（带 `?id=`） | 61 | 三 |
| `/album/ai` | AI 整理建议 | 62 | 三 |

> 落点：`apps/mobile/lib/app/router/app_router.dart` 的 `chromeByPath`（L39-54）逐条追加 `'<path>': chromeImmersive`；`_tabIndex`（L141-147）按域归位（`/car*` 归「生活」Tab；`/album*` 归「生活」Tab；`/ledger/add`、`/ledger/auto` 归「生活」Tab）。

---

### 15.3 一期 · 记账扩展（`API-015~017` + `APP-027~029` `APP-041`）

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| `API-015` | **待确认账单产品级读 / 写接口** | 后端 | P0 | — | `GET /ledger/pending`（条目 / 金额 / 商家 / **AI 判断** / 来源）、`POST /ledger/pending/{id}/confirm`（可带改后分类）、`POST /ledger/pending/{id}/ignore`。**复用 `app/services/ledger/pending.py` 既有语义**（`PENDING_PREFIX`、`load_pending` / `clear_pending` 不改）；零 `app/repositories` 依赖 |
| `API-016` | **记账智能读面** | 后端 | P0 | — | `GET /ledger/auto-summary`（本月自动记账笔数 / 分类准确率 / 待确认数）、`GET /ledger/rules`（别名规则：关键词 → 类目）、`GET /ledger/classify-preview?note=`（备注 → 分类预览）。⚠️ **准确率与「修正 N 次」须有真实来源，无来源则不出该字段**（§3.5 缺口 20） |
| `API-017` | **「养车」分类种子** | 后端 | P0 | — | `app/character/asuna/ledger_categories.py::SEED_CATEGORY_TREE` 新增**「养车」父类目 + 子项**（充电 / 加油 / 停车 / 过路 / 保养 / 洗车）与别名；评估 `app/services/tool/builtin.py::LEDGER_SOURCES`（L71）是否需扩展来源值 |
| `APP-041` | **设计系统扩展：记账族** | 设计系统 | P0 | `APP-002` `APP-007` | 按 skill **A31**（entry 功能入口行卡）、**A32**（seg / amount / kind / form / pad / save）、**A33**（stat / confirm / rule）落成组件 + golden；复用既有 `AiCard` / `CategoryBar` / `TxRow` / `ChipButton`。**纪律**：金额 `tabular-nums`；保存按钮用 ink 深色，**禁 ai 渐变** |
| `APP-027` | **手动记账页（33）** | 页面 | P0 | `APP-041` `API-016` | `features/ledger/presentation/ledger_add_page.dart` + 路由 `/ledger/add` + skill **B10**；`ledger_repository.dart` 增手动记账写方法（`POST /ledger/entries`）与分类列表读 |
| `APP-028` | **AI 自动记账页（34）** | 页面 | P0 | `APP-041` `API-015` `API-016` | `ledger_auto_page.dart` + 路由 `/ledger/auto` + skill **B11**；**来源区块按 D14 呈诚实未接入态**（三条来源标注不可用原因 + 语音记账标为可用），**禁止**渲染「已连接 / 今天同步 N 笔」 |
| `APP-029` | **账本页双入口（31 改）** | 页面 | P0 | `APP-041` `API-016` | `ledger_page.dart` 在 AI 观察卡后插入 A31 双入口；AI 自动记账入口副文案用**真实笔数**（无数据时改诚实措辞） |

**一期验收口径**：从账本页双入口进 33，填金额 + 分类 + 备注保存后，**账本页数字立刻一致**；进 34 能看到**真实待确认条目**并可确认 / 修改 / 忽略；任一统计数字无来源时呈**空态或省略**，不出现伪造值。

---

### 15.4 二期 · 车辆域（`API-018~020` + `APP-030~033` `APP-042`）

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| `API-018` | **车辆域建域与迁移 `0003`** | 后端 | P0 | — | ⚠️ **落点已按 §15.12 A1 修正**：ORM 表进 **`app/core/db.py`**（4 张 `car_*`，与 `LedgerEntryRow` L1498 / `LifeTaskRow` L1544 同级；全仓 51 张表集中于此），pydantic 域模型进 **`app/models/car.py`**；`migrations/versions/0003_car_domain.py`（`revision="0003"`、`down_revision="0002"`，`create_check_constraint` **传完整布尔式**）；`tests/support/schema_pins.py` 同步 `MIGRATION_HEAD` / `SCHEMA_TABLE_COUNT` / `SCHEMA_COLUMNS_DIGEST` + 钉测用例名升级。**不触碰** `world_*` / `memories` / `relationship_state` / `loop_runs` |
| `API-019` | **车辆费用入账与养车聚合** | 后端 | P0 | `API-017` `API-018` | 养车费用经 `app/services/ledger/service.py::record_entry`（L40-42）+ `resolve_account_id`（L122）落账，**不建第二套记账**（D12）；车辆页「本月养车支出」按**子类目**聚合，**聚合在服务端完成** |
| `API-020` | **车辆域产品级 API** | 后端 | P0 | `API-018` | `app/api/v1/car.py`（档案 / 车贷 / 保养记录 / 里程 CRUD + 提醒计算）+ `app/api/v1/schemas.py` 模型 + `app/api/v1/router.py` 注册；零 `app/repositories` 依赖；**限行按 D19 为用户手动配置**；**提醒按 D20 复用本地通知，参数类设置（禁 `*_enabled`）** |
| `APP-042` | **设计系统扩展：车辆族** | 设计系统 | P0 | `APP-002` `APP-007` | 按 skill **A34**（loan-card，深色 + warm 进度条，**禁 ai 渐变**）、**A35**（type-scroll，选中描边用类型语义色 55%）、**A37**（timeline，**末行必须为未发生态**）落成组件 + golden；`app_icons.dart` 按 `apps/mobile/docs/icons.md` 流程补车辆 / 充电类 Lucide 图标 |
| `APP-030` | **车辆主页（35）** | 页面 | P0 | `API-019` `API-020` `APP-042` | `features/car/presentation/car_page.dart` + 路由 `/car` + skill **B12**；`features/car/data/car_repository.dart` 自建数据面（**禁 import `features/ledger`**，先例 `life_repository.dart` / `chat_ledger_repository.dart`） |
| `APP-031` | **养车记一笔（36）** | 页面 | P0 | `API-019` `API-020` `APP-042` | `car_add_page.dart` + 路由 `/car/add` + skill **B13**；表单字段随类型切换（充电 = 度数 / 站点；里程 = 本次 / 总里程；保养 = 项目 / 下次里程）；**联动口径常驻** |
| `APP-032` | **车辆档案（39）** | 页面 | P0 | `API-020` `APP-042` | `car_profile_page.dart` + 路由 `/car/profile` + skill **B16**；⚠️ **文案按 D13 改口径**（`pages/39-car-profile.html:125` 的「都在本机」**不得原样落地**） |
| `APP-033` | **生活页车辆入口（30 改）** | 页面 | P0 | `APP-030` | `features/life/presentation/life_page.dart` 宫格新增车辆卡（摘要为**真实数据或诚实空态**）；**日历 / 旅行按 D21 呈诚实未接入态**（禁「15:00 方案对齐」类伪造摘要）。⚠️ **与 `APP-040` 同改一个文件，两者串行执行、不得并行编辑**（§15.12 A8） |

**二期验收口径**：记一笔养车费用后，**车辆页支出条与账本页养车分类数字一致**（同源同口径）；车辆档案与保养时间线可读写、时间线末行为「下一次保养」未发生态；生活页车辆卡摘要非伪造；**迁移钉测全绿且 `alembic upgrade head` 产出的 schema 与 ORM metadata 逐列一致**。

---

### 15.5 三期 · 相册域（仅本机，`APP-034~040` + `APP-043`）

> **状态（2026-10-01）**：8/8 **代码完成**并过全量自动化（`flutter test` `+293 -2` = 既有红基线、`analyze` 零 issue、D18 守卫绿）；执行细节见 `v5.1-task-checklist.md` §10，真机人工项见 `v5.1-manual-regression-checklist.md` §4。

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| `PLT-007` | **Flutter 工具链修复与相册依赖可行性验证** | 前置验证 | P0 | — | 修复本机 `flutter pub get / analyze / test`（根因：flutter_tools 在 `generateCommands` 阶段定位 Android SDK，`where.EXE aapt` 子进程创建失败，`process_win.cc:744`；见 `reviews/progress-audit-2026-09-29.md` §7.7）；验证原生相册库在当前约束（`sdk: ^3.13.4`）下可 `pub get` 并跑通**最小读相册 demo**（授权 → 读数量 → 读缩略图）。**产出结论报告；结论直接决定三期能否开工** |
| `APP-034` | **album 域与本机相册数据面** | 端侧 | P0 | `PLT-007` | `features/album/{data,domain}`：原生相册库接入 + 系统权限申请 + **后台 isolate** 本机分析（**过期截图 + 重复保存**，D16）+ 端侧元数据存储（**不复用已死的 `LocalStores`**，见 `progress-audit` §7.6）；`test/scaffold/layer_guards_test.dart` **登记 album 域**（L32-41）；**新增 D18 守卫**：`lib/features/album/**` 禁止 import `core/network/**` 与 `package:dio` |
| `APP-043` | **设计系统扩展：相册族** | 设计系统 | P0 | `APP-002` `APP-007` | 按 skill **A36**（storage / album / photo / actionbar）、**A38**（sug，张数 + 体积成对 + 判定理由）落成组件 + golden；`app_icons.dart` 补相册 / 照片 / 相机类 Lucide 图标 |
| `APP-035` | **相册主页（37）** | 页面 | P0 | `APP-034` `APP-043` | `album_page.dart` + 路由 `/album` + skill **B14**；文案按 **D17**（删除后进系统「最近删除」）；「仅本机」口径常驻（红线 9） |
| `APP-036` | **批量管理（38）** | 页面 | P0 | `APP-034` `APP-043` | `album_manage_page.dart` + 路由 `/album/manage` + skill **B15**；**AI 未选的原片必须可见**（opacity .55）；**相似连拍分组按 D16 呈诚实未支持态** |
| `APP-037` | **相簿详情（60）** | 页面 | P0 | `APP-034` `APP-043` | `album_detail_page.dart` + 路由 `/album/detail` + skill **B18**；按拍摄日期分组 + 视频时长徽章；连拍相关标记按 D16 呈诚实态 |
| `APP-038` | **单张照片（61）** | 页面 | P0 | `APP-034` `APP-043` | `photo_view_page.dart` + 路由 `/album/photo` + skill **B19**；大图**不切深色底**；信息行逐项标注「本机读取 / 本机归类」 |
| `APP-039` | **AI 整理建议详情（62）** | 页面 | P0 | `APP-034` `APP-043` | `album_ai_page.dart` + 路由 `/album/ai` + skill **B17**；**只呈现已实现类别**（过期截图 / 重复保存），相似连拍按 D16 呈诚实态；四条整理原则 |
| `APP-040` | **生活页相册入口（30 改）** | 页面 | P0 | `APP-035` | `life_page.dart` 宫格新增相册卡（**真实张数 + 「仅本机」** 或诚实空态）。⚠️ 与 `APP-033` **同改一个文件**，两者**串行执行、不得并行编辑** |

**三期验收口径**：授权后可读到本机相册**真实张数**；AI 预选**可推翻**、删除走系统「最近删除」；**任意相册页零网络请求**（D18 守卫测试 + `PLT-004` 走查双证）；**相似连拍区块呈诚实未支持态**；本机分析在后台 isolate 且**可中断、中断不改变任何照片**（缺口 28）。

---

### 15.6 依赖与关键路径

```text
PLT-007（工具链修复 + 依赖可行性）────────────────────────┐
                                                          ↓
一期：API-017 ─┐                                 三期：APP-034 ─→ APP-035 ─→ APP-040
              ├─→ API-019 ─┐                              ├─→ APP-036 / APP-037
API-015/016 ──┴───────────┼─→ 二期：API-018 ─→ API-020 ──┼─→ APP-038
                          │                              └─→ APP-039
APP-041（记账族）─→ APP-027 / APP-028 / APP-029          APP-043（相册族）─↗
APP-042（车辆族）─→ APP-030 / APP-031 / APP-032 ─→ APP-033
```

**关键路径**：`PLT-007 → APP-034 → APP-035 → APP-040`（三期工具链门槛最长）；后端侧最长为 `API-017 → API-019 → API-020 → APP-030`。

**四个收口点**：

| 收口点 | 判定标准 |
|---|---|
| **V1**（一期末） | 账本双入口闭环：33 保存后账本数字一致；34 待确认可确认 / 忽略；**无伪造同步数据** |
| **V2**（二期末） | 同源同口径：车辆页养车支出与账本养车分类数字一致；迁移 `0003` 上链且钉测全绿 |
| **V3**（三期末） | 仅本机可验证：`album` 域禁网络守卫绿 + 相册页零网络请求；相似连拍呈诚实态 |
| **V4**（全量） | 24 个任务全部可追溯到 `traceability.md` §13 的行；`flutter analyze` + `flutter test` 真跑通过；后端零回归（基线对照法） |

### 15.7 阻塞清单（🚫 未闭环不得开工）

| # | 阻塞项 | 阻塞任务 | 闭环判据 |
|---|---|---|---|
| 1 | 设计系统 skill 内部相册数值不一致（B14/B15 vs B17/B18） | `APP-036` `APP-039` | 端侧按 B17/B18 + `pages/` 自洽口径实现，**skill 回写登记待办**（`traceability.md` §13.5 V1） |
| 2 | 「所有档案都在本机」文案（`pages/39-car-profile.html:125`） | `APP-032` | 按 D13 改口径后方可实现 |
| 3 | 「不需要联网权限」表述（`pages/37-album.html:166`） | `APP-035` | 按 D17 配套口径收敛 |
| 4 | 日历 / 旅行被提升为常规模块 | `APP-033` | 按 D21 维持 🚫 后置 + 诚实未接入态 |
| 5 | 账单自动同步来源平台不可行 | `APP-028` | 按 D14 降级为诚实未接入态 |
| 6 | 相似连拍分析成本不匹配 | `APP-036` `APP-037` `APP-038` `APP-039` | 按 D16 本期不做，呈诚实未支持态，**列 V2** |
| 7 | 「仅本机」无可验证约束 | `APP-034` | 按 D18 新增分层守卫 + 零网络断言 |
| 8 | 本机 Flutter 工具链故障 | 三期全部任务 | `PLT-007` 产出结论报告 |

> **2026-10-01 阻塞门进展**：#1~#3 已闭环（skill `components.md` 与 `pages/37` / `pages/39` 文案按 D13 / 冲突 17 / §13.5 V1 回写）；#4~#6 已在实现中按 D14 / D16 / D21 裁决落地；#7 随 `APP-034` 落地（D18 守卫）；#8 已闭环（`PLT-007` 命令面 + `photo_manager` demo 三步验证通过，报告 §7）——**三期（`APP-034~040` / `APP-043`）解除阻塞，可开工**。

### 15.8 迁移与铁律检查（V5.1 逐项过 §10 检查表）

- [x] 新 API 是否**零** `app/repositories` 依赖？→ `API-015`~`API-020` 全部走 `app/services/*`，同 `tasks.py` / `memory.py` 先例
- [x] 新增设置项是否为**参数类**（非 `*_enabled`）？→ 车辆提醒提前量 / 限行配置均为参数类（D19 / D20）
- [x] 新增事件类型是否已登记 `EXPECTED_EVENT_TYPES`？→ **本次零新事件类型**（待确认账单走 HTTP 读写，不改流式契约）
- [x] 是否触碰 `loop_runs.steps` 键集？→ **否**
- [x] 是否新增迁移？→ **是，`0003`（车辆域）**：`create_check_constraint` 传完整布尔式；钉测升级清单 = `MIGRATION_HEAD` / `SCHEMA_TABLE_COUNT` / `SCHEMA_COLUMNS_DIGEST` / `test_migration_chain_head_is_still_00NN` 用例名（`tasks/support/schema_pins.py`）；**执行前先 `git worktree` 测 blast radius**（约 22 条跨版本钉测）
- [x] 是否改动 `world_*` / `memories` / `relationship_state` / `loop_runs`？→ **否**
- [x] `services` 是否 import `app.application`？→ **否**
- [x] 新增 `runtime_*` 字段是否登记 `V30_RUNTIME_FIELDS`？→ **本次无**
- [x] 零回归是否用**基线对照法**验证？→ 是（判据 = 当前失败集 ⊂ 基线失败集）
- [x] 新建 `app/` / `tests/` 文件是否转了 CRLF？→ 是；`docs/**` 保持 LF
- [x] 是否误用 `git rm`？→ **禁止**（删文件用 `find <file> -delete`）；提交后复核 `git rev-parse HEAD`
- [x] 移动端是否真跑了 `flutter analyze` + `flutter test`？→ **`PLT-007` 修复前不得以静态检查替代**（`tasks.md` §0.4 / `progress-audit` §6.2 明文禁止）

### 15.9 Task Detail 生成记录（决策 D22 及其执行偏离）

> **原决策 D22**：只出任务注册表，逐任务 Detail 在**各期开工前**生成。
> **执行结果（2026-09-30）**：**24 个 Detail 已一次性全部生成**（见 §11.1 索引）。这是一次**对 D22 的显式偏离**，理由与影响见下表；`requirements-analysis.md` §6.1 的 `D22` 行须同批回写。

| 项 | 说明 |
|---|---|
| 体例依据 | 与 41 个既有明细**同规范**：`tasks/README.md` 的 10 章体例 + 三条任务线差异化要求（`APP-*` 引用 skill 组件/页面编号；`API-*` 写字段级契约并留痕 §10 铁律检查表；`PLT-*` 写可复现验收） |
| **偏离 D22 的理由** | ① 用户明确要求「对 tasks 的任务拆解」；② 24 个任务的**上游已全部冻结**（`traceability.md` §13 矩阵 + §6.1 决策 + §3.5 裁决），不存在"等现状定稿"的悬空项；③ 一次性生成使三期的**跨任务接口一致性**（如 `hint` 由服务端下发、相似连拍统一呈未支持态、隐私口径三页逐字一致）可被统一裁决，分期生成反而易分叉 |
| **偏离的代价（须认领）** | 分期生成能随实现漂移而微调，一次性生成后改动需**回改 Detail**；缓解：每份 Detail 的 §4.2 都写明"待实现期求证/回填"的证据项（如 `API-017` §10 的两条待证事项、`API-016` §4.2 裁决 2 的准确率求证），把不确定项显式化而非隐藏 |
| 反向约束 | Detail 的 `In Scope` 必须落在 §15.3~§15.5 的「交付面」范围内；**新增能力须先回改 §15 + `requirements-analysis.md` + `traceability.md` §13**（顺序不可颠倒，见 `traceability.md` §12） |
| 生成后校验 | 逐份核对 §10「需求溯源」能否在 `traceability.md` §13 找到对应行 → **24/24 全部可核对**（结果见 §15.12） |

### 15.10 任务编号占用登记

| 任务线 | §12~§14 已占用 | V5.1 新增（本节） | 下一可用号 |
|---|---|---|---|
| `APP-` | `APP-026` | `APP-027`~`APP-043`（17 个） | `APP-044` |
| `API-` | `API-011`~`API-014`、`API-021`（§16） | `API-015`~`API-020`（6 个） | `API-022` |
| `PLT-` | `PLT-001`~`PLT-006` | `PLT-007`（1 个） | `PLT-008` |
| `IDENT-` | `IDENT-001`~`IDENT-009`（`010`/`011` 为 P2 留白） | — | `IDENT-012` |

### 15.11 待回写台账（本轮发现，非本注册表能自行了结）

| # | 事项 | 归属 | 处置 |
|---|---|---|---|
| 1 | **41 个 Task Detail 状态行全部失真**（2026-09-23 生成后未回写，实际约 16 个已达真实现） | `tasks/*.md` | 与 V5.1 增量注册同批校订（`progress-audit-2026-09-29.md` §3.1 / §5 P2） |
| 2 | **v5.0.0 无验收报告 / 进度台账** | `docs/version/v5.0.0/` | 补验收台账（`progress-audit` §3.3 / §5 P2） |
| 3 | **旧迁移号描述未回写折叠事实**（本文件 §0.3 与 §12~§14 仍出现 `0055`~`0058`） | 本文件 | §0.3 已补 V5.1 行；历史编号**保留不改**（`tasks.md` §0.3 顶部已有说明） |
| 4 | ~~**skill 相册数值待修正**（B14/B15 的「12 张 / 8 张 / 4 张」）~~ | `.agents/skills/zhaoxi-design-system/references/components.md` | **已闭环（2026-10-01）**：B14/B15 已按 B17/B18 的 76 = 38+26+12 口径回写；B14/B17/B18「不需要联网权限」同步收敛 |
| 5 | ~~**`pages/37-album.html:166` / `pages/39-car-profile.html:125` 文案待修正**~~ | `design/pages/` | **已闭环（2026-10-01）**：37 页按冲突 17 收敛；39 页按 D13 改口径（skill B16 复述同步） |
| 6 | ~~**`PLT-007` 的工具链结论须回写 `PLT-001` 式报告**~~ | `apps/mobile/docs/` | **已闭环**：报告 2026-09-30 产出（`plt007-toolchain-report.md`）；依赖面（`photo_manager` demo）结论 2026-10-01 补记 |

### 15.12 Detail 生成期的上游修正与零偏离声明（2026-09-30）

> 24 份 Detail 撰写时按证据发现 **9 处上游表述需修正**。这些**不是明细擅自扩张**，而是本节与 `requirements-analysis.md` / `traceability.md` 的回写项（顺序纪律见 `traceability.md` §12）。

| # | 事项 | 涉及任务 | §15 原表述 | 实际证据 | 处置 |
|---|---|---|---|---|---|
| **A1** | **OR M 表落点** | `API-018` | `app/models/car.py（车辆档案 / 车贷 / 保养记录 / 里程）` | 全仓 ORM 表**集中定义在 `app/core/db.py`**（`LedgerEntryRow` L1498 / `LifeTaskRow` L1544 等 51 张表）；`app/models/**` 只放 pydantic 域模型（`app/models/ledger.py:52-117`） | **已回写 §15.4**：表进 `app/core/db.py`，域模型进 `app/models/car.py` |
| **A2** | 仓储未列 | `API-019` | 目录结构未列 car 仓储 | 与 `ledger_repository` 同级约定 | 已在 `API-019` §6.1 登记 `app/repositories/car_repository.py` |
| **A3** | 设置域文件未列 | `API-020` | §15.4 只写「参数类设置」 | 设置按域拆分（先例 `app/core/settings/ledger.py:7-15`、`email.py`） | 已在 `API-020` §6.1 登记 `app/core/settings/car.py` |
| **A4** | 组件文件名未列 | `APP-041/042/043` | 目录结构只写 `lib/design_system/components/` | 三个族的组件需落到具体文件 | 已在三份 Detail §6.1 定为 `entry_card.dart` / `ledger_input.dart` / `ledger_auto.dart` / `car_cards.dart` / `car_input.dart` / `timeline.dart` / `album_cards.dart` / `album_report.dart` |
| **A5** | **跨域通道缺失** | `APP-040` | 未含应用级状态文件 | 相册张数是**纯端侧数据**（§2.4：后端零端点），而 `layer_guards_test.dart:49` **禁止 `features/life` import `features/album`** → 需要一个既非跨域 import、又非后端的通道；`lib/app/state/` 已存在（`persona_mode.dart`）且现有 9 条守卫未对其设限 | 已在 `APP-040` §6.1 新增 `lib/app/state/album_summary_provider.dart`（album 写 / life 只读） |
| **A6** | 三层目录占位 | `APP-034` | 未提 `presentation/` | `layer_guards_test.dart:20` 断言 `features/<domain>/{data,domain,presentation}` **三层目录存在** | 已在 `APP-034` §6.1 登记 `features/album/presentation/.gitkeep`（由 `APP-035` 填实） |
| **A7** | **分类重名风险（D15 细化）** | `API-017` `API-019` | §15.4 说「新增『养车』父类 + 子项（充电 / 加油 / 停车 / 过路 / 保养 / 洗车）」 | 既有 `ledger_categories.py:12-13` **已有 `交通/加油`（别名含「洗车」「充电桩」）与 `交通/停车`** → 同名子项会被 `ensure_seed_categories` 静默跳过，且迁移既有节点会破坏既有用户数据 | 已在 `API-017` §4.1 定子项名 `加油费` / `停车费`（别名含口语），并在 `API-019` §4.2 裁决 1 加**读侧显式映射**（养车子树 ∪ `交通/加油` ∪ `交通/停车`） |
| **A8** | 同文件冲突 | `APP-033` `APP-040` | 两者均登记改 `life_page.dart` | 同文件并行编辑会互相覆盖 | 已在两份 Detail §1 / §4.2 标注 **串行执行、不得并行** |
| **A9** | **对 D22 的偏离** | 全部 24 份 | D22：只出注册表，Detail 分区生成 | 用户要求本次完成拆解，且上游已全部冻结 | 已在 §15.9 记录偏离理由与代价；`requirements-analysis.md` §6.1 的 `D22` 行须同批回写 |

**生成后校验结果**：

| 校验项 | 结果 |
|---|---|
| 10 章体例完整（缺一节即不合格，`tasks/README.md:19`） | 24/24 完整 |
| §10「需求溯源」可在 `traceability.md` §13 找到对应行 | **24/24 可核对**（无凭空发明） |
| §3.2 Out of Scope ≥5 条且每条给理由 | 24/24 满足 |
| §6.3 红线点名具体路径 | 24/24 满足 |
| 现状断言带 `文件:行号` | 24/24 满足（无法当场求证的已显式标注"待实现期回填"，见 `API-016` §4.2 裁决 2、`API-017` §10） |
| 跨任务一致性（`hint` 服务端下发 / 相似连拍统一未支持态 / 隐私口径三页逐字一致） | 已统一裁决并在对应 Detail 落条款 |

**须回写清单**（本注册表已就地改 A1 / A8；其余见各 Detail）：`requirements-analysis.md` §6.1 的 `D22` 行（A9）；`.agents/skills/zhaoxi-design-system/references/components.md` 的 B14/B15 相册数值（`traceability.md` §13.5 V1，设计侧）；`design/pages/37-album.html:166` 与 `design/pages/39-car-profile.html:125` 的文案（V3 / V4，设计侧）。

---

## 16. 增量注册：首页每日 AI 总结生成器（`API-021`，2026-10-07 立项，未开工）

> **背景**：2026-10-07 代码审核发现首页 AI 结论卡名不副实：`/home/summary` 的 `insight` 区块数据源是 reflection 的**长期用户洞察**（`insights_query.list_insights(domain="home")` 按置信度排序、**无日期窗口**），既非「今日」也非「总结」；且全系统不存在任何每日总结生成器（briefing 仅有天气 + 任务卡）。曾同批做**诚实文案收口**（标题→「AI 洞察」等）并登记 DEV-05；**同日用户裁决改回产品话术**（标题→「今日 AI 总结」、跳转→「查看完整早间简报 →」、端上空态→「今天还没有新的总结」），并落地**无洞察时的确定性兜底**（天气 + 任务数，经 `briefing/compose.current_weather_for_user` 服务端定位链，缺项省略、全空才出空态）。本任务仍需落地真正的每日总结能力；**落地后 DEV-05 回撤**。

| Task ID | 名称 | 交付面（概要） | 状态 |
|---|---|---|---|
| `API-021` | 每日总结生成器 + 首页读面升级 | ① 生成器：**昨日**口径汇总（账本支出/笔数/分类 + 任务完成情况，会话记忆可选），确定性拼装、零编造（沿 `briefing/compose.py` 的逐卡降级纪律；LLM 叙事后置）；② 存储：带业务日期的每日总结表（增量迁移按链尾顺延，注册时链尾 `0008`）；③ 读面：`/home/summary` 的 `insight` 区块升级——有昨日总结时下发日期话术标题（如「昨日的总结」）与叙事，无则沿现有回落链（洞察 → 天气 + 任务兜底 → 空态）；④ 端上预期**零改动**（标题与叙事均由服务端下发，同 DEV-03 思路） | 未开工 |

**约束与纪律**：

- 红线 11「诚实未接入」优先于设计稿 1:1：任一数据源缺失逐项省略，不补占位叙事；`design/pages/` 首页原型的示例文案（`principles.md:83`）仍是目标形态，落地时按真实数据源收敛。
- 生成时机（夜间 life loop 步骤 vs 早间首次请求惰性生成）是 Detail 裁决项，倾向**惰性生成**（无 cron 依赖）；新设置按领域命名，禁 `*_enabled`。
- 按 D22 原纪律：Task Detail 于**开工前**生成；届时按变更顺序回写 `requirements-analysis.md` 与 `traceability.md` §13（顺序不可颠倒）。
- 落地后同批处置：`design-alignment-report.md` DEV-05 回撤、`test_design_principles.py` 静态断言与 `components.md` A2 卡标签话术同步。
