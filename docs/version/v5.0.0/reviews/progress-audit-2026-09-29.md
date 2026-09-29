# V5.0.0 实现度审查报告（2026-09-29）

> **性质**：全量进度审查（只读，不产码）。对象 = `tasks.md` 注册的 41 个正式任务（APP-001~025 / API-001~010 / PLT-001~006）+ §12~§14 三个增量注册，对照 `apps/mobile` / `apps/backend` 实际代码逐项核实。
> **方法**：三路并行核查（后端 API 面 / 移动端页面与数据层 / PLT 与文档声明），甄别「端点存在但返回占位」「页面在但数据写死」「引擎写好但触发链断」「pubspec 声明但零使用」四类情况，全部结论带 `file:line` 证据。
> **一句话结论**：地基与对话闭环是真材实料（真实现约 17/42 ≈ 40%）；「空有架子」集中在 M2/M3 的产品表面层——约 13 处假数据与断链；M4 整段仍在 PLT-001 门控后（刻意留空，非隐瞒）；41 个 Task Detail 状态行全部失真。

---

## 1. 总体分布

| 里程碑 | 真实现 | 半成品 | 纯架子 | 门控 / 退役 |
|---|---|---|---|---|
| M0 地基（8） | APP-001/002/003/006/007/008 | APP-004（drift 未接线）、APP-005（外部深链未配） | — | — |
| M1 对话（7） | API-001（邮箱登录形态）/002/003、APP-010/011 | APP-009（会话列表缺）、APP-012（mode 不上云，任务书内裁剪） | — | API-001 配对码按 §13 退役（替代链路为真） |
| M2 生活域（9） | API-005/006、APP-017（大部分）/018 | API-004、API-007、APP-014、APP-016 | APP-015、APP-022 | — |
| M3 主动（6） | APP-018 | API-008、APP-019/020/021 | （APP-022 归 M2 行） | — |
| M4 健康（5） | — | — | APP-024/025 + `health.py` stub | API-009/010、APP-023 按 D1 刻意留空 |
| PLT（6） | — | PLT-002（调研完成）、PLT-004（大部分）、PLT-005（CI 建好） | PLT-003、PLT-006 | PLT-001 探针真 / 报告未出，**门控仍关闭** |

## 2. 「空有架子」实锤清单（按严重度）

### 2.1 页面在、数据是假的（6 处，P0）

| # | 位置 | 问题 |
|---|---|---|
| 1 | `apps/mobile/lib/features/home/presentation/home_page.dart:282-296` | 首页三宫格 `healthAuthorized=true` 分支写死 `7h12m / 62bpm / 6,234`（设计稿示例值），违反任务书 APP-014「不得用假数据」红线；`home_page_test.dart:68` 将假值断言固化 |
| 2 | `apps/mobile/lib/features/life/presentation/life_page.dart:79-143` | 生活页六张模块卡 AI 摘要全部写死（「12 条 · AI 已整理」等）；`features/life/data/` 仅 `.gitkeep` |
| 3 | `apps/mobile/lib/features/life/presentation/capture_route.dart:27-36` | 快速捕获「已归到『记账』」是本地 setState，零后端调用、零 AI 意图归类（APP-022 核心诉求未实现） |
| 4 | `apps/mobile/lib/features/profile/presentation/profile_page.dart:281-291` | 主动关怀三开关 `AppToggle(value: …, onChanged: (_) {})` 写死 no-op，不持久化不调度 |
| 5 | `apps/mobile/lib/features/health/presentation/health_consent_page.dart:32` | 健康授权开关写死 no-op，无同意持久化（APP-025 为 P0） |
| 6 | `apps/mobile/lib/features/chat/presentation/chat_ledger_page.dart:12` | AI 记账页纯占位 `Text('chat-ledger …')` |

### 2.2 引擎真、触发链断（4 处，P1）

| # | 位置 | 问题 |
|---|---|---|
| 7 | `apps/mobile/lib/features/briefing/data/local_brief_notifier.dart` | `zonedSchedule` 实现完整，但 `scheduleDaily` 全仓零调用点——无任何 UI 能设定时刻，通知永不触发（叠加 #4 → M3 收口点 C4 不可达） |
| 8 | `apps/mobile/lib/core/storage/`（drift 7 表 + 3 仓储 + 测试均真） | 运行时零接线：`ChatHistoryCache` 无构造点、`BriefingRepository()` 不注入缓存、`openInMemory` 仅测试用 |
| 9 | `apps/mobile/lib/features/profile/presentation/privacy_page.dart:37-90` | 文案承诺「服务端与本地缓存同步删除」但本地清空函数（`local_stores.dart:40-44`）零调用；导出结果拿到即丢弃 |
| 10 | 组件装配缺位 | ResultCard（结果卡+快捷 chips）零使用；会话列表 `sessions` 从未写入（`chat_page_state.dart:54`）；记忆页编辑为「原样 PATCH」空转（`memory_page.dart:116`） |

### 2.3 后端「字段/能力是声明的，不是产出的」（3 处，P1）

| # | 位置 | 问题 |
|---|---|---|
| 11 | `apps/backend/app/api/v1/home.py:121-135` | `/home/summary` 8 区块中 AI 总结 / 问候 / Orb 状态语为硬编码占位（含「昨晚睡得不错」假健康表述）；真实仅任务与今日消费两块 |
| 12 | `apps/backend/app/api/v1/memory.py:23-24` | `source_count` / `usage_receipts` schema 声明但全仓无产出点（恒空）；「遗忘」为物理删除而非任务书要求的「置 forgotten 可审计」（`memory_repository.py:233-239`） |
| 13 | `apps/backend/app/api/v1/briefing.py` | 「按设定时刻预生成」未实现（请求时合成），「供本地通知离线取用」验收项不成立 |

## 3. 文档与台账问题

1. **41/41 个 Task Detail 状态行全为「未开工」**（2026-09-23 生成后未回写）；实际约 17 个已达真实现。
2. 三个信息源互相矛盾：Detail 状态行 vs `reviews/v5.0.0-code-review.md`（09-24 时点「仅 2/41 达标」，已过时）vs git log 实际进展；§12~§14 增量以「已实现」登记，与旧状态行双轨并存。
3. **v5.0.0 无验收报告 / 进度台账**；tasks.md 旧迁移号（0055~0058）描述未回写 09-29 折叠为 `0001+0002` 的事实。
4. `traceability.md` 的 82 个 ✅ 为「覆盖关系已建立」，非「已完成」，易误读。

## 4. 确认扎实的部分（无需返工）

- **移动端**：分层守卫测试、设计 token（ThemeExtension 双主题、features 零硬编码色值）、Orb（缺 56 尺寸档）、NDJSON 流式（跨 chunk / UTF8 边界、16ms 节流、断流恢复）、邮箱登录全链路（Redis 验证码 + SMTP + Keystore）。
- **后端**：`tool_step` 事件独立通道、`life_tasks` 全 CRUD、insights 真查 DB、IDENT-001~009 身份收口与声明逐项吻合、邮箱验证码登录三层链路。
- **CI**：真跑 golden（30 张）+ codegen diff 门禁 + 后端 fast 套件。

## 5. 整改优先级

| 级 | 事项 |
|---|---|
| P0 | #1 三宫格假数据切空态分支（PLT-001 结论前）+ 修固化断言；#3~#6 假交互接真或显式降级 |
| P1 | #7~#10 触发链接通（通知调度入口、drift 注入、本地清空联动、ResultCard/会话列表/记忆编辑）；#11~#13 后端占位字段真实化 |
| P2 | 回写 41 个 Detail 状态行、补 v5.0.0 验收台账、修正迁移号描述 |

> **附**：PLT-001 真机验证仍未执行（探针已就绪，见 `apps/mobile/docs/plt001-probe.md`）；M4 门控在结论产出前维持关闭。
