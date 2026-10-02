# 朝夕 App · 设计稿对齐报告

> **时点**：2026-10-02（**2026-10-03 追加 §7**：底部导航 5 位与「动态」位）｜ **分支**：`feat/design-car-album` ｜ 本轮实现分支 `feat/dynamic-tab`（同级 worktree）
> **审核对象**：`design/`（现役 `design/pages/*.html`，23 页）↔ `apps/mobile/lib`
> **权威顺序**：`.agents/skills/zhaoxi-design-system/`（最高）> `design/pages/` > `design/ai-life-agent-design.html`
> 本文件是设计稿对齐的**唯一汇总文档**（已合并原 audit / tasks 两份）。

---

## 0. 摘要

| 项 | 状态 |
|---|---|
| 最大问题 | 生活宫格 3×3 含 4 个**悬空入口**（任务/日历/旅行无页面、记忆已降级），违反红线 10 |
| 后续变更（2026-10-03） | 底部导航改 **5 位**（首页 / 动态 / 对话 / 生活 / 我的），第 2 位「动态」可变、默认记账；生活页去捕获条 / Skill 文案 / 即将上线区，改「3 列宫格内拖动重排，第一格即动态位」设置动态位（明细见 §7） |
| 本轮已交付 | 宫格收敛为 6 格；补齐备忘录(41)/日程(42) 两页；AI 标识组件层（✦）对齐；账本页单一「记一笔」；健康页 IA 重排；全仓 Material 图标清零 |
| 已完成 | DA-01~DA-16 / DA-19 / DA-22 / DA-23 / DA-25 / DA-27 / DA-28 / DA-29 / DA-30（2026-10-03 两批收口，明细见 §3 勾选态） |
| 被后端卡住 | 健康域真实内容（DA-26 卡 `PLT-001` + `/health/sync` no-op）、DA-21（`tool_step` 持久化）、DA-15 之「关系 Lv.N」（无轻量关系端点，待裁决） |
| 有意偏差 | DEV-01~04 已裁决「保留增强、登记偏差」；DA-08「加标签」/ DA-10「✦ 徽章与地点」按 D16 呈诚实未支持态 |
| 剩余待办 | DA-20 / DA-21 / DA-26（卡后端或产品裁决） |
| 静态校验 | `flutter analyze` **0 issue**；后端 unit + v50 + golden **1671 过**，integration **432/433**（唯一失败为已登记既有红 `http_lifecycle`，先于 V5.1） |
| 验证 | `flutter test` **347 全绿**；本批 golden 无 diff（`entry_row` 取景为账单行，EntryCard 图标变更未入景） |

---

## 1. 本轮已交付

### 1.1 生活宫格 9 格 → 6 格（红线 10）

原宫格 3×3 含 `任务` / `日历` / `旅行` / `记忆`，其中前三者**没有对应页面**（悬空入口），
`记忆` 已于 2026-09-30 降级为「我的」子页、不应占宫格。现按设计稿收敛为 3×2：

| 位置 | 模块 | 落点 | 底色 / 图标色 token |
|---|---|---|---|
| 1 | 记账 | `/ledger` | `tileMoney` / `money` |
| 2 | 备忘录 | `/memo`（新增） | `tileAi` / `aiPrimary` |
| 3 | 日程 | `/schedule`（新增） | `tileInfo` / `aiBlue` |
| 4 | 健康 | `/health` | `tileHeart` / `heartFg` |
| 5 | 车辆 | `/car` | `tileInfo` / `aiBlue` |
| 6 | 相册 | `/album` | `tileWarm` / `warm` |

「即将上线」3 个占位（阅读 / 习惯打卡 / 更多 Skill）保留，图标由 Material 改 Lucide。**〔2026-10-03 修订〕该区块已整块移除**（见 §7.2）。

### 1.2 新增两页（41 / 42）

- `features/life/presentation/memo_page.dart` — 备忘录：返回 → 标题 + 计数胶囊 → 副标题 →
  快速捕获条 → AI 结论卡「亚丝娜整理中」→ 按 `tag` 分组清单（无 tag 时不编造主题，统一落「全部备忘」）→ 隐私口径卡；长按可删。
- `features/life/presentation/schedule_page.dart` — 日程：返回 → 标题 → 迷你周日历 → AI 结论卡「亚丝娜的排法」→ 今日时间线 → 即将到来。
- 新增 `design_system/components/schedule_cards.dart`（A40 日程族：`WeekStrip` / `ScheduleTimeline` / `NextCard`）、A39 `CountPill` / `MemoRow`。
- 两页**复用任务域 `/tasks`**（`kind=memo` / `kind=task`），沿用 V5.0.0 `APP-022`「V1 不建独立备忘录域」降级裁决，未新增后端域。
- 诚实处理：无日期待办落时间线末位标「**待排**」；备忘录无来源时间就不显示来源行。

### 1.3 AI 标识组件层（红线 1 / 7）

- 新增 `components/sparkle.dart`：`SparkleIcon` + `SparklePainter`（✦ 四芒星，`tokens.md` 固定路径 / 24 坐标系）。
- `AiCard` 补设计稿 `.ai-card .tag`：✦ 13px + 12px/700 aiPrimary，字距 0.72，下间距 9。
- 替换 `ModeChip` / `MemHint` / `AskPill` / `CaptureBar` / `ProcCard` 的 `Icons.auto_awesome`；Tab 栏删除私有 `_SparklePainter` 改用同一组件。
- **全仓剩余 13 处 Material 图标清零** → Lucide（`rows.dart` / `proc_card.dart` / `privacy_page` / `health_consent` / `health_probe` / `home_page` / `ledger_page`）。

### 1.4 账本页单一「记一笔」（IA 裁决 2）

- `EntryCard` 由竖版改 **A31 横版行卡**（38 图标 + 标题/副文案 + 右侧 chevron）；新增 `SyncLink`（A31 sync-link）。
- 账本页两个并列入口合并为单「记一笔」+「本月已自动记 N 笔 · 同步与 AI 规则 ›」。
- 补「需要你的确认」块（`LedgerConfirmRow`，按 `reason` 出招：确认 / 修改 / 忽略）。
- **「待确认」从 34 迁回 31** —— `components.md` B11 明确「待确认不在这里」；34 改为纯二级管理页（来源 + 规则），AI 结论改为「拿不准的已放在账本首页等你确认」。
- `CategoryBar` 改四色轮转（money / blue / purple / green）。
- 修 bug：`direction` 枚举（`expense`）原样抛给用户 → 转中文（支出 / 收入）。

### 1.5 首页与健康页（部分交付）

- 首页：头像 `Icons.person` → 字母头像（设计稿 `远`）；健康 hint 改读 `health.source`，后端未填则不显示（不编造设备名）。
- 健康页：按 B6 重排为「**AI 状态解读优先**（原先排在最后，违反红线 4）→ 睡眠趋势 → 今日指标 → 来源声明」；
  新增 `components/insight_hero.dart`（`InsightHero`，`insightHero` 渐变 + 评分标签）与 `features/health/data/health_repository.dart`（读 `/health/score`）；未授权走诚实空态、不出任何数值；常驻免责保留。

### 1.6 提交记录

| commit | 说明 |
|---|---|
| `9be73c6` | 记账明细抽取与底部导航记忆页对齐 |
| `7252a6c` | 生活宫格收敛六格并补齐备忘录日程页 |
| `7e90666` | 落设计稿对齐待选任务清单 |
| `8f03735` | 账本单入口、AI 标识组件与返回键图标化 |

> `8f03735` 还包含一项**非本会话产生**的改动：`BackLink` 由 `Text('‹ 返回首页')` 文本前缀改为
> `Icon(AppIcons.chevronLeft, 18)` + 4px + 裸 label，并同步改掉全仓 14 处调用方、重生成 `a30_back.png`、
> 更新 `goldens_test.dart` / `car_add_page_test.dart`。已验证：无残留 `'‹ '`、静态分析干净。

---

## 2. 有意偏差（已裁决：保留增强，登记偏差）

以下与 `design/pages/` 不一致但**保留**，不再作为待办，也不要当缺陷改回去：

| ID | 位置 | 偏差 | 保留理由 |
|---|---|---|---|
| DEV-01 | 养车记一笔（36） | 多出 `LedgerPad` 金额键盘（设计无） | 键盘录入体验增强 |
| DEV-02 | 登录页（00） | 多出「上次登录 $email」chip（设计无） | 便利性 |
| DEV-03 | 简报页（11） | 标题由服务端驱动（设计为固定「早上好，我整理好了你的今天。」） | 服务端可运营 |
| DEV-04 | 我的页（50） | 「状态异常提醒」用「即将开放」文案代替开关 | M4 门控（健康未接入） |

---

## 3. 剩余待办

**图例** — 改动量：S（≤1 文件/纯文案）· M（单页/单组件）· L（跨页或多组件）｜Golden：是否需重生成

### P1 · 功能缺口（数据源已在，可直接开工）

- [x] **DA-06 记一笔「说给亚丝娜 / 键盘输入」双模** — `ledger_add_page.dart`：缺 seg 切换、say-box + 示例 chip、解析卡「我听到的」。**L**｜`ledger_add`
- [x] **DA-07 对话页消息后建议 chip 行** — `chat_page.dart`：缺「查看行程 / 调整预算 / 换个人少的目的地」。**M**｜无
- [x] **DA-08 相册批量管理补全** — `album_manage_page.dart`：缺「全选」、过期截图/相似连拍/手动挑选**分组 + 组标签**、「移动」「加标签」、预选 ai-hint 与回指 62。**L**｜无
- [x] **DA-09 相簿详情补全** — `album_detail_page.dart`：缺 AI 整理卡、`✦` 连拍原片徽章、批量管理按钮、隐私卡；日期头缺地点/视频段数。**L**｜无
- [x] **DA-10 单张照片补全** — `photo_view_page.dart`：缺「我留了这张」`✦` 徽章、AI 说明卡 + chip 行、「照片信息」标题、底部 收藏/移到相簿/删除 actionbar。**L**｜无
- [x] **DA-11 AI 整理建议页对齐** — `album_ai_page.dart`：补底部隐私卡、建议行集合。**M**｜无
- [x] **DA-12 车辆页指标与配色** — `car_page.dart`：指标标签改「本月充电 186 kWh / 百公里电耗 / 总里程」；`CategoryBar` 四色；记录行强调色。**M**｜`car_page`
- [x] **DA-14 车辆档案微调** — `car_profile_page.dart`：section hint 文案；补 AiCard 的「看本月养车账 →」。**S**｜`car_profile`

### P2 · 文案小差异（低风险）

- [x] **DA-15 我的页对齐** — `profile_page.dart`：身份行补「· 关系 Lv.N」；「健康数据授权」→「数据授权」+ 副文案；「记忆管理」副文案补条数；「隐私设置」副文案改「本地优先 · 一键清空 · 导出数据」。（状态开关按 DEV-04 保留；**「关系 Lv.N」未做**：`/state` 是全量快照不宜为一条文案调用，待后端出轻量端点；「隐私设置」副文案按 skill B8 已定口径去「本地优先」，落「一键清空 · 导出数据」）**S**｜无
- [x] **DA-16 验证码页文案** — `verify_code_page.dart`：重发倒计时 `48 s`→`48s`；隐私文案已是 skill 定稿口径（用户控制权、无「本地优先」），维持现状。**S**｜无

### P3 · 需产品 / 架构裁决或后端改动

- [x] **DA-25 首页数据可视化 · 后端契约扩展**（2026-10-03）：`/home/summary` 补 `spend.week_bars`（ledger 域新增 `daily_expense_series`，冲正口径同 `sum_signed_minor`，负日截 0）与 `MetricCell.spark`（DA-26 接入前恒空）；端上已接，无下发不渲染。DB 环境实测可用
- [ ] **DA-26 健康域真实内容** — 睡眠趋势 7 柱 / 今日指标三行 / 综合评分。**前置**：`PLT-001` 通过、`/health/sync` 真正落库（当前是 no-op 骨架，`authorized` 恒 false）
- [x] **DA-19 日程「完成态」**（2026-10-03）：`GET /tasks` 加 `status=open|done|all`（默认 open 向后兼容；all 含 open+done、不含软删 cancelled），TaskOut 补 `completed_at`；端上日程页拉 all，done 项限当日（有当日日期或今日完成），无提醒的完成项时间标签取完成时间，跨天旧完成项不上时间线
- [ ] **DA-20 备忘录「过期清理建议」** — 需过期判定 + 建议数据源
- [ ] **DA-21 对话 · AI 记账 4 步 ProcCard** — 需 `tool_step` 持久化
- [x] **DA-22 文档修订** — `docs/version/v5.0.0/traceability.md:480` 仍写「生活宫格 3×3 / 日历·旅行后置」，加 2026-09-30 裁决修订注记。**S**
- [x] **DA-23 Skill 模板补齐** — `.agents/skills/zhaoxi-design-system/assets/app_tokens.dart` 缺 `danger` / `dangerBg` / `dangerText`。**S**

### P4 · 本轮新发现（低优先）

- [x] **DA-27 账本「最近账单」逐行语义色**（2026-10-03）：映射实际已由设计稿 31 隐含定稿（餐饮=money / 交通=aiBlue / 购物=aiPrimary，娱乐沿用 green），无需产品再裁决；端上经 `/ledger/categories` 解析 id→名称后进 `ledger_category_visuals` 映射，未识别分类回落 money 基线
- [x] **DA-28 记一笔图标**（2026-10-03）：`pencil` 字形已在 `fonts/lucide.ttf` cmap 内，ICONS 表登记 + 脚本重生成即得（未动字体资产本身）；账本页「记一笔」EntryCard 改 `AppIcons.pencil`，字体守卫测试过
- [x] **DA-29 组件测试补 SparkleIcon / InsightHero** — 新组件目前只被页面测试间接覆盖。**S**

### P5 · 验证（需可用 Flutter 环境）

- [x] **DA-30 重生成 golden + 全量回归**（2026-10-03 已执行：工具链恢复，`flutter test` 342 全绿；实际变更 golden 16 张 + 新增 3 张，`a6_task` / `a9_tabbar` 无 diff 属正常）

  ```bash
  cd apps/mobile
  flutter test --update-goldens     # regen 后建议 review diff
  flutter test && flutter analyze
  ```

  **受影响 golden 清单**（渲染已变，必须重生成）：
  - 设计系统：`a2_ai_card`、`a6_task`、`a8_ask_pill`、`a10_mode_chip`、`a11_mem_hint`、`a14_proc`、`a17_capture`、`ledger_entry`
  - **新增**：`ledger_sync_link`（需生成）
  - 功能页：`life_page_modules`、`ledger_auto`、`ledger_auto_no_accuracy`、`ledger_add`、`ledger_page_entry_row`、`car_page`、`car_add`、`car_profile`
  - `a9_tabbar` 预期**不变**（✦ 路径与尺寸一致）；若 regen 后无 diff 属正常

### 依赖关系速查

- DA-06 与 DA-01 同属记账域，DA-01 已改入口结构，DA-06 接着改录入页最顺
- DA-02 / DA-03 已改组件层 → 所有含 AiCard / CaptureBar / MemHint / ModeChip / AskPill / ProcCard 的 golden 都要重生成（见 DA-30）
- DA-25 / DA-26 同属「后端契约与健康域」，建议合并推进；DA-26 卡 `PLT-001`
- DA-19 / DA-20 / DA-21 卡后端契约
- DEV-01~04 已裁决保留，不计入待办

---

## 4. 完整差异审核清单（按页）

### 4.1 已确认缺口（对应上面的 DA 项）

| 页面 | 差异 |
|---|---|
| 健康（32） | 4 个空占位，缺 insight-hero / 睡眠趋势 7 柱 / 今日指标 3 行；副标题文案不同 → **DA-05 已重排 IA，内容待 DA-26** |
| 首页（10） | `weekBars` 空数组 → 周柱状图不渲染；`MetricCard` 无 sparkline；健康 hint 文案；头像用 `Icons.person` → **DA-04 已修头像与 hint，可视化待 DA-25** |
| 账本（31） | 缺「需要你的确认」；两并列入口；`CategoryBar` 全 money → **DA-01 已修** |
| 记一笔（33） | 缺「说给亚丝娜 / 键盘输入」seg、say-box + 示例 chip、解析卡「我听到的」→ **DA-06** |
| 对话（20） | 缺消息后建议 chip 行；输入提示文案不同 → **DA-07** |
| 对话 · AI 记账（21） | 缺「正在记账」4 步 ProcCard 与 chip 行（已知：`tool_step` 未持久化）→ **DA-21** |
| 相册批量管理（38） | 缺「全选」；单层 GridView vs 分组 + 组标签；缺「移动」「加标签」；缺预选 ai-hint 与回指 62 → **DA-08** |
| 相簿详情（60） | 缺 AI 整理卡、`✦` 徽章、批量管理按钮、隐私卡；日期头缺地点/视频段数 → **DA-09** |
| 单张照片（61） | 缺「我留了这张」徽章、AI 说明卡 + chip 行、「照片信息」标题、actionbar → **DA-10** |
| AI 整理建议（62） | 缺底部隐私卡；建议行集合不同（相似连拍本期未开启）→ **DA-11** |
| 车辆（35） | 指标标签不同；`CategoryBar` 四色；记录行强调色 → **DA-12** |
| 养车记一笔（36） | 多出键盘（→ DEV-01 保留）；AI 提示组件/顺序不同 |
| 车辆档案（39） | section hint 文案；缺 AiCard「看本月养车账 →」→ **DA-14** |
| 简报（11） | 标题服务端驱动（→ DEV-03 保留）；多出城市设置行 |
| 我的（50） | 身份行缺「关系 Lv.」；「数据授权」行名与副文案；「记忆管理」缺条数；「隐私设置」副文案 → **DA-15** |
| 验证码（01） | 隐私文案不同；重发倒计时多一个空格 → **DA-16** |
| 登录（00） | 多出「上次登录」chip（→ DEV-02 保留） |

### 4.2 组件层

| 项 | 状态 |
|---|---|
| `AiCard` 缺 `.ai-card .tag`（✦ + aiPrimary 12px/700） | **已修** |
| `CaptureBar` / `ModeChip` / `MemHint` / `AskPill` / `ProcCard` 用 Material `auto_awesome` | **已修**（改 `SparkleIcon`） |
| 全仓 Material 图标 13 处 | **已清零** |
| `EntryCard` 竖版 vs A31 横版 | **已修** |
| 缺 A31 `sync-link` | **已新增** |
| 缺 A39 `count-pill` / `memo` 行 | **已新增** |
| 缺 A40 日程族 | **已新增** |
| 缺 `insight-hero` 组件（有 token 无组件） | **已新增** |

### 4.3 文档 / Skill 同步（已做）

- `references/tokens.md` §1.4：语义色表补 **token 名列**（`tileAi` / `tileHeart` / `heartFg` 等），并注明「健康 / 完成」（青绿 `health`）与「健康（心）」（心红 `heartFg`）是**两套语义**。
- `assets/app_tokens.dart`：同步补 `heartFg`（仍缺 `danger` / `dangerBg` / `dangerText` → DA-23）。
- `SKILL.md`：新增「实现侧已裁决保留的偏差」段（DEV-01~04），防止后续被当缺陷改回。
- 新增 `app_colors.dart` token `heartFg`（浅 `#F06A6A` / 深 `#FF8A8A`）。

---

## 5. 验证状态与环境注意事项

| 项 | 结果 |
|---|---|
| `flutter analyze`（2026-10-03 工具链恢复） | ✅ **0 issue** |
| `flutter test`（2026-10-03） | ✅ **342 全绿**（含 golden） |
| Golden | ✅ 已重生成：更新 16 张（a2/a8/a10/a11/a14/a17/ledger_entry/car×3/ledger×4/life_page_modules 等），新增 `ledger_sync_link` / `sparkle_icon` / `insight_hero`；`a6_task` / `a9_tabbar` 渲染未变无 diff 属正常 |
| 前会话遗留红（工具链故障期掩盖，本轮一并修复） | memo 测试「生活」撞名、ledger 测试「餐饮」撞名、chat_ledger 测试对含 Orb 页面用 pumpAndSettle 永不收敛、schedule NextCard 日期块 4px 溢出、chat_ledger 断言 `48 s` 空格 |

### 5.1 本机 Flutter 工具链故障（重要）

`flutter analyze`、`flutter test`、`dart analyze`、`dart run` 均在**启动阶段崩溃**：

```
ProcessException: 所有的管道范例都在使用中 (CreateFile failed 231)
```

原因是 Dart/Flutter 无法 spawn 子进程（Windows 管道耗尽），与代码无关。

**绕过方法**（已验证可用）：

```bash
# 直接跑 VM，跳过 dartdev 的二次 spawn
dart --disable-dart-dev --packages=.dart_tool/package_config.json <script.dart>
```

配合 `package:analyzer` 的 `AnalysisContextCollection` + `getResolvedUnit` 做**进程内静态分析**。
探针保留在 `.workbuddy-ai/tmp/probe_analyze.dart`（gitignored）：

```bash
cd apps/mobile
/d/SDK/flutter_windows_3.29.2-stable/flutter/bin/cache/dart-sdk/bin/dart --disable-dart-dev \
  --packages=.dart_tool/package_config.json \
  /d/workspace/aICustomerAgent/.workbuddy-ai/tmp/probe_analyze.dart lib test
```

注意：analyzer 13.3.0 用 `result.diagnostics`（`errors` 已废弃），`Severity` 用 `.name` 字符串比较可免导入。

### 5.2 工作树会被外部并发改动

本轮发现 `BackLink` 被外部（非本会话）重构并被 `git add -A` 卷入提交。
**建议**：提交前先看 `git status --porcelain` 是否出现自己没动过的文件；提交信息要覆盖实际内容。

---

## 6. 待裁决 / 待确认

1. **DA-26 健康域**：`PLT-001` M4 门控 + `/health/sync` 落库（当前 no-op，`authorized` 恒 false）。
2. **DA-21 AI 记账 4 步 ProcCard**：需 `tool_step` 持久化（后端 + 历史链路）。
3. **DA-20 备忘录过期清理建议**：需先定「过期」口径与数据源。
4. **DA-15 之「关系 Lv.N」**：需后端轻量关系端点（`/state` 是全量快照，不宜为一条文案调用；stage stranger→partner 序号 +1 即 Lv，映射已备好）。

> 2026-10-03 结案：DA-25 后端契约与端上已打通（DB 环境实测可用）；DA-27 映射由设计稿 31 隐含定稿、无需产品裁决；DA-28 未动字体资产（字形已在 cmap 内）。

---

## 7. 2026-10-03 · 底部导航 5 位与「动态」位（IA 变更）

> 触发：用户裁决把底部导航改为 5 位，并引入可配置的「动态」槽；同批把生活页收敛为纯工具箱。
> 实施方式：从 `feat/design-car-album` 的 HEAD 切出同级 worktree（分支 `feat/dynamic-tab`）隔离开发。

### 7.1 真源先行（skill → 原型 → 代码）

| 层 | 文件 | 变更 |
|---|---|---|
| Skill（最高） | `.agents/skills/zhaoxi-design-system/SKILL.md` | 红线 10 由「主 Tab 永远 4 个」改为「主 Tab 固定 5 个 + 第 2 位可变动态槽」；新增「信息架构裁决（2026-10-03）」5 条；2026-09-30 第 1 条标注被取代；同日三轮裁决最终把动态位设置手势定为**只拖到置顶区** + 动效（见 §7.4） |
| Skill | `references/components.md` | A9 改 5 位（悬浮球落到 5 位里的第 3 位、整栏居中）+ 动态槽为投放目标；A17 注明仅备忘录页在用；A18 增「长按拖动 / 置顶区变体」；B1 第 11 条；B4 重写为「生活工具箱（置顶区 + 5 格宫格）」 |
| Skill | `references/flutter-mapping.md` · `references/tokens.md` | M3 禁令第 5 条改 5 位口径；`fillMuted` 用途表述更新 |
| 原型 | `design/pages/10-home.html` · `30-life.html` · `32-health.html` · `50-profile.html` | Tab 栏补「动态」槽（默认「记账」）；30 删捕获条 / Skill 文案 / 即将上线区，改「3 列 6 格宫格（第一格即动态位）」+ 拖动提示 |
| 原型 | `design/pages/index.html` · `design/README.md` | 页面索引与拆分说明同步 5 位口径与拖动语义 |

`design/ai-life-agent-prototype.html`（冻结存档）未改。

### 7.2 客户端实现

| 层 | 文件 | 变更 |
|---|---|---|
| 状态 | `lib/app/state/dynamic_tab.dart`（新增） | `LifeModule` 注册表（6 项：id / 名称 / 图标 / 二级页路由）+ `lifeModuleOrderProvider`（模块顺序，**首位即动态位**）+ 派生 `dynamicModuleProvider`；暴露 `promote()`（置顶）并读写 `PrefsStore` |
| 状态 | `lib/app/router/dynamic_tab_page.dart`（新增） | `/dynamic` 宿主页：按动态位渲染 6 个模块之一，统一 `showBackLink: false` |
| 路由 | `lib/app/router/app_router.dart` | `chromeByPath` 增 `/dynamic`；`_AppShell` 改 `ConsumerWidget` 并注入动态位文案 / 图标；`_tabIndex` / `_onTap` 重写为 5 位（`/health` 由首页位纠正为生活位） |
| 组件 | `lib/design_system/components/app_tab_bar.dart` | `tabCount` 4 → 5；新增 `dynamicLabel` / `dynamicIcon`（默认记账）；**纯展示、不含投放目标**（首版曾加 `DragTarget` + 悬停高亮，三次裁决后移除） |
| 组件 | `lib/design_system/components/chips.dart` | `ModuleCard` 增 `active`（动态位 ✦ 徽标） |
| 页面 | `lib/features/life/presentation/life_page.dart` | 删捕获条与 `capture_route` 依赖、删「Skill 化 · 可持续扩展 / 即将上线 / Skill 商店」、副标题改「你的生活工具箱」；首屏 = **3 列 6 格宫格**（第一格即动态位）；网格自算坐标（`Stack` + `AnimatedPositioned`），长按拖动中其余卡片 240ms 实时让位、松手落位回弹，拖起放大 1.05 + 深阴影 + 触感反馈；健康卡由 `go` 改 `push` |
| 页面 | ~~`lib/features/life/presentation/dynamic_module_sheet.dart`~~ | 首版「设为动态」底部面板，**同日二次裁决后删除**（改为拖拽，见 §7.4） |
| 页面 | ledger / car / album / memo / schedule 五个模块页 | 新增 `showBackLink`（默认 `true`，为 `false` 时隐藏「‹ 生活」） |
| 存储 | `lib/core/storage/prefs_store.dart` | 新增 `life.module_order` 键（逗号分隔模块 id）并登记进 `allKeys` |
| 启动 | `lib/app/bootstrap.dart` | 启动时 `restore()` 模块顺序 |

健康页无 `BackLink`，无需改；`CaptureBar` / `CaptureRouteSheet` 组件保留（备忘录页仍在用）。

### 7.3 验证

| 项 | 结果 |
|---|---|
| `flutter analyze lib test` | ✅ 0 issue |
| `flutter test` | ✅ **357 全绿**（`dynamic_tab_test` 覆盖顺序 / 置顶 / 重排 / 持久化 / 非法值回落；`life_page_test` 覆盖拖动置顶与 6 卡结构；`components_test` 断言动态槽是投放目标） |
| Golden | ✅ 重生成 `goldens/a9_tabbar.png`（5 位、悬浮球整栏居中）与 `goldens/life_page_modules.png`（动态位置顶区独享一行带 ✦ 徽标 + 其余 5 格宫格） |

### 7.4 交互调整（2026-10-03，共四次）：抽屉 → 拖动 → 置顶区 → 宫格重排 + 让位动效

| 轮次 | 裁决 | 落地 |
|---|---|---|
| 一 | 「设为动态」底部面板（长按弹面板 6 选 1） | `dynamic_module_sheet.dart`（后删除） |
| 二 | 改为拖动，且必须拖到底部导航第 2 槽才生效 | 导航栏加 `DragTarget<Object>` + `onDynamicDrop`（后移除） |
| 三 | 改为只拖到**独立置顶区** | 置顶区独占一行（后取消） |
| 四（最终） | 置顶区占位显空 → 改 **3 列宫格内重排**，并参考 react-beautiful-dnd 补让位动效 | 见下表 |

| 项 | 最终形态 |
|---|---|
| 布局 | **3 列 2 行**（6 格），**不设单独一行的置顶区**；第一格即动态位，右上角 ✦「动态」徽标随拖动预览实时移动 |
| 拖动实现 | 网格自算坐标：`Stack` + `AnimatedPositioned`（不用 `Draggable`——它缺 `onDragUpdate` 级别的实时位置，做不出让位） |
| 让位动效 | 手指位置 → 最近格 → 预览顺序；其余卡片 240ms `easeOutCubic` 补间让位（对齐 react-beautiful-dnd 的 move transition） |
| 拖起反馈 | 卡片放大 1.05 + `elevation.deep` 阴影；其余卡片降至 0.72 透明度；`HapticFeedback.selectionClick()` |
| 落位回弹 | 拖动卡的 `AnimatedPositioned` 由 `Duration.zero` 切回 240ms → 从手位补间回目标格（对齐 drop animation）；`mediumImpact` 触感 |
| 提示行 | 常驻「长按卡片拖动重排 · 第一格就是底部导航的「动态」」；拖动中换成「松手放到想放的位置 · 第一格会成为「动态」」（aiPrimary 色 + 160ms 淡入） |
| 状态模型 | `lifeModuleOrderProvider` 持有 `List<LifeModule>`（首位即动态位），暴露 `moveTo(from, to)`；存储键 `life.module_order` |
| 为什么不用现成库 | Flutter 官方只有列表版 `ReorderableListView`；第三方网格库（`reorderable_grid_view` / `flutter_reorderable_grid_view`）面向「同容器重排」但要求固定尺寸与自管布局，本场景要同时呈现真实摘要与拖动预览，自绘 `Stack` 更可控；设计系统亦要求全自绘 |

---

## 8. 2026-10-03 · 生活页与车辆页设计稿改版同步（第二轮）

> 触发：`design/pages/30-life.html` 与 `design/pages/35-car.html` 更新了一版（`31-ledger.html` 相对仓库无改动，不在本轮范围）。
> 本轮不含信息架构变更，只做 UI 对齐 + 一条新纪律。

### 8.1 真源先行

| 层 | 文件 | 变更 |
|---|---|---|
| Skill（最高） | `SKILL.md` | 新增**红线 11 诚实未接入**：原型里的示例数值（健康评分 / 续航 / 电量 / 车机互联 / 充电趋势 / 环比 / 可清理张数）无真实数据源时不得照抄 —— 文案写「尚未接入」或整行不渲染，图形类（迷你柱状图、环形进度）无数据宁可不画；AI 结论卡只允许用已获取的真实数据拼装 |
| Skill | `references/components.md` | A2 增「动作行」（1~2 枚 chip 的主 / ghost 规格）；A18 增「第三行 trend」并规定主摘要只放事实；A19 增 cat-note 注脚（只允许用已算出的占比）；B4 重写（Hero + AI 生活小结 + 区块标题 + 六格 trend）；B12 重写（AI 观察置顶 + 车辆 Hero + 电量环 + 分类条包卡片 + 注脚） |

`design/pages/30-life.html`、`35-car.html` 属设计侧改版，客户端只做同步、未回改原型。

### 8.2 客户端实现

| 层 | 文件 | 变更 |
|---|---|---|
| 组件 | `design_system/components/cards.dart` | `AiCard` 增 `secondaryActionLabel` / `onSecondaryAction`：有第二动作时按 A2 渲染成 chip 行（无第二动作时保持原文字链接，`a2_ai_card` golden 不变） |
| 组件 | `design_system/components/chips.dart` | `ModuleCard` 增 `trend` / `trendColor`（10px/600 单行，超长省略） |
| 数据 | `features/life/data/life_repository.dart` | `LifeCarSummary` 增 `restrictionDetail`（取服务端限行提醒原文，不自己推算日期） |
| 页面 | `features/life/presentation/life_page.dart` | 新增 `_LifeHero`（本地日期 + 时段问候 + 本机称呼 + Orb md，无称呼不编造）；新增 AI 生活小结卡（真实数据拼装 + 两枚 chip：查看今日日程 / 去相册看看）；新增「生活模块 · 6 个 · 都在帮你跑」区块标题；六格接 trend（日程用今日首条待办、车辆用限行提醒，其余按红线 11 写「…尚未接入」）；卡片高度 136 → 156 以容纳第三行；主摘要随设计稿收敛为纯事实（`本月 ¥612` / `今日 2 项` / `2847 张 · 仅本机`） |
| 页面 | `features/car/presentation/car_page.dart` | AI 观察卡上移首位；新增 `_CarHero`（车型 + 车牌 chip + 续航「—」+「尚未接入车机数据」+ 空电量环「电量待接入」）；分类支出条包进 `AppCard` 并加 cat-note（用已算占比）；车辆档案副标题改「保险 / 年检 / 保养记录」（车牌已由 Hero 承载，不再重复） |

健康卡保持「趋势参考 · 非诊断」隐私口径（红线 8），第三行明示未接入。

### 8.3 未接入项（红线 11 落地记录）

健康综合分、记账环比、备忘录主题归类、相册可清理张数与整理建议、车辆续航 / 电量 / 车机互联状态、谷电时段占比、充电趋势 spark —— 客户端均无数据源：

- 前四项以卡片第三行「…尚未接入」明示；
- 车辆 Hero 用「续航约 — km」「尚未接入车机数据」「电量待接入」+ 空环取代示例值；
- **spark 直接不画**（图形无法用文字自证诚实）；
- AI 小结与 cat-note 只用已获取的真实数据（今日日程 / 本月支出 / 养车支出 / 限行提醒 / 相册张数 / 已算占比）。

### 8.4 验证

| 项 | 结果 |
|---|---|
| `flutter analyze lib test` | ✅ 0 issue |
| `flutter test` | ✅ **364 全绿**（新增 life_page 5 例、car_page 3 例；既有摘要断言随设计稿口径同步） |
| Golden | ✅ 重生成 `features/goldens/life_page_modules.png`、`features/goldens/car_page.png` 并逐张目检 |
| 过程中修复 | `ModuleCard` 加第三行后卡片固定高溢出 14px → `_tileHeight` 136 → 156；生活页 Hero 的 Orb 常驻呼吸动画使拖动测试 `pumpAndSettle` 永不收敛 → 改定时 `pump` |
