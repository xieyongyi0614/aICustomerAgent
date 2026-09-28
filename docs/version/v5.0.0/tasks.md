# V5.0.0 朝夕 App（Flutter 客户端）任务拆分

> **上游（需求依据，最优先）**：`docs/version/v5.0.0/requirements-analysis.md`（需求条目化 REQ-xxx、14 条冲突与缺口、可行性裁决、**11 条决策已全部拍定**）——**本注册表之外的任何能力均不得进入 Task Detail**。
> **上游（覆盖核对）**：`docs/version/v5.0.0/traceability.md`（设计稿 119 条要求 → REQ → 任务的**全量覆盖矩阵**，含反向核对：41 个任务全部可追溯到设计稿或调研报告）。**每个 Task Detail 生成前先在该矩阵里找到它的来源条目。**
> **上游（技术方案）**：`docs/version/v5.0.0/flutter-architecture.md`（Flutter 分层、选型、Orb 与设计 token 落地路径）。
> **上游（现状约束）**：`docs/current-system-architecture-baseline.md`；`docs/version/v4.0.0/tasks.md`（九条前提裁决）；`docs/version/v3.0.0/acceptance-report.md`（`CONDITIONAL — NOT RELEASED`）。
> **状态**：Task Registry（任务定义）+ **Task Detail 已生成（41/41）**（2026-09-23，位于 `docs/version/v5.0.0/tasks/`，体例对齐 `docs/version/v4.0.0/tasks/PLA-XXX.md`，撰写规范见 `tasks/README.md`）。索引与生成记录见 **§11**。
> **主干**：41 个任务 / 5 个里程碑 / 3 条任务线（`APP-` 客户端、`API-` 后端补齐、`PLT-` 平台横切）。
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

### 0.3 前提三：迁移纪律（本版本只加 1 个迁移）

| 项 | 内容 |
|---|---|
| 链尾现状 | `0054_life_ledger_domain.py`（**已核**） |
| 本版本新增 | `0055_life_tasks.py`（仅 `life_tasks` 一张表，服务 API-005） |
| 其余域 | 健康域若进 V1，追加 `0056_health_facts.py`；否则**零新迁移** |
| 🚨 已知陷阱 1 | `op.create_check_constraint` **必须传完整布尔式**（`f"source IN {target_check}"`），不能传值清单 → 曾致 `0045` 在 PG 上 `DatatypeMismatch`、`0052` 不可达 |
| 🚨 已知陷阱 2 | **加一个迁移会打破约 22 个跨版本钉测**（`v23/v24/v25/v26` 中的 `MIGRATION_HEAD` 常量、`test_migration_chain_head_is_still_00NN` 用例名、`SCHEMA_TABLE_COUNT`、`SCHEMA_COLUMNS_DIGEST`）→ 执行前先 `git worktree` 取干净基线测 blast radius |
| 🚨 已知陷阱 3 | `FROZEN_BLOB_SHA_BASELINE` 已空 → 改动 `profiles.py` 的 Profile 表内容会红，属**真语义变更**须显式声明 |

### 0.4 前提四：测试与验证纪律（继承仓库实测经验）

- `tests/conftest.py` autouse `_offline_repos` 把仓储指向内存 SQLite；**测试内不要 `from app.core.db import SessionLocal`**，用 `app.repositories.<x>_repository.SessionLocal`。
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
| **D6** | 新建轻量任务域（`life_tasks`，迁移 `0055`），不复用 plan step | `API-005` |
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
| APP-005 | 导航骨架与深链 | 基建 | P0 | APP-001 | go_router 声明式路由、5 Tab（首页/生活/对话悬浮球/记忆/我的）、深链映射原型 9 页 |
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
| API-005 | 任务域（`life_tasks`） | 新领域 | P0 | — | 迁移 `0055_life_tasks.py`；CRUD + 勾选完成 + 时间提醒注册 + 排序理由 | ① 迁移钉测已升级；② `SCHEMA_TABLE_COUNT` 同步；③ `create_check_constraint` 传完整布尔式；④ 零回归 |
| API-006 | **产品级洞察（Insight）读接口** | 新接口 | P0 | — | `GET /insights?domain=ledger\|health\|home&limit=N` → `{id, domain, headline, narrative, evidence[], source_refs[], generated_at}` | ① 零 `repositories` 依赖；② 无洞察时返空列表（不返 500）；③ 「AI 叙事优先」原则有真实数据源 |
| API-007 | 产品级记忆接口 | 新接口 | P0 | — | `GET /memory/items`（含 `source_kind` / `source_count` / `last_updated` / `usage_receipts[]`）+ 编辑 + 遗忘（置 `forgotten`） | ① 零 `repositories` 依赖；② 列表只含 active 且未 forgotten；③ 遗忘可审计；④ 用途回执有真实来源 |

> ⚠️ **API-005 与 API-006 需先完成 §6 决策 D5 / D6 的裁决**，否则实现口径会返工。

### 4.2 客户端

| ID | 任务 | 类型 | 优先级 | 依赖 | 交付面 |
|---|---|---|---|---|---|
| APP-013 | **Tool Call 过程卡与结果卡** | 核心组件 | P0 | API-002, APP-007 | 步骤四态渲染（done ✓ / running ◌ / todo ○ / failed ✗）、结果落点明示、结果卡 + 快捷操作 chips |
| APP-014 | **首页装配** | 页面 | P0 | API-004, APP-006, APP-013 | 问候 → Orb 英雄区 → AI 总结卡（渐变描边，视觉焦点）→ 状态三宫格 → 今日任务 → 今日消费 → 输入丸；**信息流严格「先结论、后数据、再行动」**；⚠️ **三宫格必须实现双分支**：`PLT-001` 通过走真实数据，未通过走**空态 + 引导授权**（不得留白、不得用假数据） |
| APP-015 | 生活页 | 页面 | P0 | APP-007, API-005 | 快速捕获条、模块宫格（含每模块 AI 摘要）、「即将上线」虚线占位 |
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
| API-009 | 健康数据 ingest 与存储 | 新领域 | P1 | PLT-001 | 迁移 `0056_health_facts.py`；`health_*` 三件套；ingest 工具 `builtin.health.sync` | ① **健康数据不进 memory 域**（同 V4.0.0 裁决 2 纪律）；② 命名避开既有 `services/tool/health.py`（工具熔断健康度）；③ 幂等 ingest |
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
