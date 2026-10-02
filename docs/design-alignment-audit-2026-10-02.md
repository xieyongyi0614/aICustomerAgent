# 设计稿对齐审核 · Flutter 移动端（2026-10-02）

> **后续状态**：本报告是审核时点的差异快照。已完成项、有意偏差与剩余待办以
> **`docs/design-alignment-tasks.md`**（DA-01~DA-30）为准 —— 其中 DA-01 / DA-02 / DA-03 已完成，
> DA-04 / DA-05 完成客户端与结构部分（数据可视化与健康内容分别卡后端契约与 `PLT-001` 门控），
> DEV-01~04 已裁决「保留增强、登记偏差」。

审核对象：`design/`（现役 `design/pages/*.html` 23 页）↔ `apps/mobile/lib`
权威顺序：`.agents/skills/zhaoxi-design-system/`（最高）> `design/pages/` > `design/ai-life-agent-design.html`

方法：逐页比对 HTML 结构与真实文案 vs Flutter 页面代码；组件规格以
`references/components.md` / `references/tokens.md` 为准；静态校验用进程内
`package:analyzer`（162 文件，0 error / 0 warning）。

---

## 1. 本轮已实现（结构性收敛 + 明确小修）

### 1.1 生活宫格 9 格 → 6 格（红线 10：禁止悬空入口）

原宫格 3×3 含 `任务` / `日历` / `旅行` / `记忆`，其中 `任务`、`日历`、`旅行` **没有对应页面**
（悬空入口），`记忆` 已于 2026-09-30 降级为「我的」子页、不应占宫格。现按设计稿收敛为 3×2：

| 位置 | 模块 | 落点 | 底色 / 图标色 token |
|---|---|---|---|
| 1 | 记账 | `/ledger` | `tileMoney` / `money` |
| 2 | 备忘录 | `/memo`（新增） | `tileAi` / `aiPrimary` |
| 3 | 日程 | `/schedule`（新增） | `tileInfo` / `aiBlue` |
| 4 | 健康 | `/health` | `tileHeart` / `heartFg` |
| 5 | 车辆 | `/car` | `tileInfo` / `aiBlue` |
| 6 | 相册 | `/album` | `tileWarm` / `warm` |

「即将上线」3 个占位（阅读 / 习惯打卡 / 更多 Skill）保留，图标由 Material 改 Lucide。

### 1.2 新增两页（补齐 41 / 42）

- `features/life/presentation/memo_page.dart` — 备忘录（41）
  返回「‹ 生活」→ 标题 + 计数胶囊 → 副标题 → 快速捕获条 → AI 结论卡「亚丝娜整理中」
  → 按 `tag` 分组的备忘清单（无 tag 时不编造主题，统一落「全部备忘」）→ 隐私口径卡。
  长按任意一条可删除（走 `DELETE /tasks/{id}`）。
- `features/life/presentation/schedule_page.dart` — 日程（42）
  返回「‹ 生活」→ 标题 → 迷你周日历 → AI 结论卡「亚丝娜的排法」→ 今日时间线 → 即将到来。

两页**复用任务域 `/tasks`**（`kind=memo` / `kind=task`），沿用 V5.0.0 `APP-022` 的
**「V1 不建独立备忘录域」降级裁决**，未新增后端域。

无日期数据的诚实处理：备忘录无来源时间就不显示来源行；日程把「无日期待办」落时间线末位并标
**「待排」**，不编造时间。

### 1.3 设计系统新增

- `design_system/components/schedule_cards.dart`（A40 日程族）：`WeekStrip`（迷你周日历）、
  `ScheduleTimeline` + `ScheduleTimelineItem`（今日时间线，时间戳左置 + 卡片间连线 + 完成态删除线 + 徽章）、
  `NextCard`（即将到来卡）。
- `design_system/components/chips.dart` 追加 A39 `CountPill`（计数胶囊）、`MemoRow`（备忘行）。
- `app_colors.dart` 新增 `heartFg` token（浅色 `#F06A6A` / 深色 `#FF8A8A`）。
  「健康 / 完成」的青绿 `health` 与「健康（心）」的心红 `heartFg` 是**两个语义**，此前项目只有
  `tileHeart` 底色、缺图标色 token，本次补齐。
- `life_repository.dart`：`LifeTaskItem` 扩展 `tag` / `note` / `remindAt` / `dueDate`，
  新增 `completeTask()`。

### 1.4 明确小修

- 记账 · 同步与 AI 规则（34）：第 3 个统计项 `待你确认` → **`学会的规则`**（条数取 `GET /ledger/rules`），
  区块 hint 同步为「来自你的 N 次修正」。
- 相册（37）：「最近添加」月份渲染 bug —— `2026 月 9 月` → **`9 月`**。
- 路由：新增 `/memo`、`/schedule`（沉浸式、无 Tab 栏），并归入生活 Tab 索引组。

---

## 2. 仍存在的差异

### A. 需产品 / 架构裁决（未动）

| # | 位置 | 差异 | 说明 |
|---|---|---|---|
| A1 | `docs/version/v5.0.0/traceability.md:480` | 仍写「生活宫格 3×3 / 日历·旅行后置」 | 已被 2026-09-30 IA 裁决取代。属历史版本台账，**未改**；如需可加修订注记 |
| A2 | 日程页「完成态」 | 后端 `GET /tasks` 只返**未完成**任务 | 设计稿时间线含已完成项（删除线）；接口不返回 done，故该态在真实数据下不会出现（代码已支持，等接口扩展） |
| A3 | 备忘录「过期清理建议」 | 设计稿 AI 卡含可执行的「删掉它 / 先留着」 | 需过期判定与建议数据源，当前无；本轮 AI 卡改为**不编造**的诚实结论 |

### B. 已确认缺口（可直接开工，本轮未做）

| # | 页面 | 缺口 |
|---|---|---|
| B1 | 健康（32） | **内容桩**：4 个 `_HealthSection` 空态占位（「连接手环后…」），缺设计稿的 insight-hero（综合评分 + 叙事）、睡眠趋势 7 柱、今日指标 3 行（静息心率 / 步数 / 运动）；副标题文案也不同 |
| B2 | 首页（10） | `SpendSummary.weekBars` 传空数组 → **周柱状图不渲染**；`MetricCard` 未用 sparkline；健康 hint「来自已连接设备」vs 设计「来自小米手环 9 Pro」；头像用 `Icons.person`（应为字母头像，且违反 Lucide 红线） |
| B3 | 账本（31） | 缺「需要你的确认」块；两个 `EntryCard`（手动记一笔 / AI 自动记账）vs 设计**单一「记一笔」+ sync 次级入口**；`CategoryBar` 全用 `barMoney`，设计为四色 |
| B4 | 记一笔（33） | 缺「说给亚丝娜 / 键盘输入」seg、say-box + 示例 chip、解析卡「我听到的」、状态分隔行 |
| B5 | 对话（20） | 缺消息后建议 chip 行（查看行程 / 调整预算 / 换个人少的目的地）；输入提示文案不同 |
| B6 | 对话 · AI 记账（21） | 缺「正在记账」4 步 ProcCard 与 chip 行。**已知原因**：`tool_step` 未持久化，代码注释已声明 |
| B7 | 相册批量管理（38） | 缺「全选」；单层 GridView vs 设计的过期截图 / 相似连拍 / 手动挑选**分组 + 组标签**；缺「移动」「加标签」动作；缺预选 ai-hint 与「这些预选是怎么算出来的 →」回指 62 |
| B8 | 相簿详情（60） | 缺 AI 整理卡、`✦` 连拍原片徽章、批量管理按钮、隐私卡；日期头缺地点 / 视频段数 |
| B9 | 单张照片（61） | 缺「我留了这张」`✦` 徽章、AI 说明卡 + chip 行、「照片信息」标题、底部 收藏 / 移到相簿 / 删除 actionbar；信息行字段不同 |
| B10 | AI 整理建议（62） | 缺底部隐私卡；建议行集合不同（相似连拍本期未开启，代码有 D16 说明） |
| B11 | 车辆（35） | 指标标签不同（设计：本月充电 186 kWh / 百公里电耗 / 总里程）；`CategoryBar` 四色；记录行强调色应逐行不同 |
| B12 | 养车记一笔（36） | 多出 `LedgerPad` 键盘（设计无）；AI 提示为 `AiCard` 而设计是行内 `ai-hint`；区块顺序不同 |
| B13 | 车辆档案（39） | section hint 文案不同；缺 AiCard 的「看本月养车账 →」链接 |
| B14 | 简报（11） | 标题服务端驱动 vs 设计固定「早上好，我整理好了你的今天。」；多出「天气按实时定位 · 点按设置」行 |

### C. 文案 / 视觉小差异

| # | 位置 | 差异 |
|---|---|---|
| C1 | 我的（50） | 身份行缺「· 关系 Lv.3」；「数据授权」行名与副文案不同（设计「管理亚丝娜可以读取的数据范围」）；「记忆管理」副文案缺条数（设计「128 条 · 查看、编辑、遗忘」）；「隐私设置」副文案（设计「本地优先 · 一键清空 · 导出数据」）；「状态异常提醒」设计是**开关**，现为「即将开放」文案（M4 门控） |
| C2 | 验证码（01） | 隐私文案不同；重发倒计时 `'$_countdown s'` 多一个空格 |
| C3 | 登录（00） | 多出「上次登录 $email」chip（设计无） |
| C4 | 组件层 `AiCard` | 设计 `.ai-card .tag` 是 **✦ + aiPrimary 12px/700 标签行**（AI 身份标识）；现仅渲染标题，少了 AI 视觉标记 |
| C5 | 组件层 `Icons.auto_awesome` | `CaptureBar` / `ModeChip` / `MemHint` 仍用 Material 图标，tokens.md 要求 AI 相关一律用 **✦ 四芒星固定路径**（现仅有 Tab 栏私有的 `_SparklePainter`，宜抽为公共组件） |

---

## 3. 验证状态

| 项 | 结果 |
|---|---|
| 进程内静态分析（lib + test，162 文件） | ✅ **0 error / 0 warning** |
| 设计系统守卫（无硬编码色 / 无 Material `Colors.` / 无跨 feature import / 无 w550·w650·w750） | ✅ 人工核对通过 |
| `flutter analyze` / `flutter test` | ⛔ **本机工具链故障，未能执行**（见下） |
| Golden | ⛔ 3 张待重生成 |

**工具链故障**：本机 Flutter/Dart 无法 spawn 子进程（Windows `CreateFile failed 231 —
所有的管道范例都在使用中`），`flutter analyze`、`flutter test`、`dart analyze`、`dart run`
均在启动阶段崩溃。已用 `dart --disable-dart-dev` 直连 VM + `package:analyzer` 做进程内替代校验。

**需在可用环境执行**：

```bash
cd apps/mobile
flutter test --update-goldens test/features/life_page_test.dart \
  test/features/ledger_auto_page_test.dart   # 重生成 3 张 golden
flutter test test/features/memo_page_test.dart test/features/schedule_page_test.dart
flutter test && flutter analyze
```

待重生成的 golden（渲染已变）：
- `test/features/goldens/life_page_modules.png`（宫格 9→6）
- `test/features/goldens/ledger_auto.png`（统计项改「学会的规则」）
- `test/features/goldens/ledger_auto_no_accuracy.png`（同上）

其余 golden（`test/design_system/goldens/*`、car / album / ledger_add / orb）**不受影响** ——
本次未改动任何既有组件的渲染。

---

## 4. 文档与 Skill 同步

- `references/tokens.md` §1.4：语义色表补 **token 名列**（`tileAi` / `tileHeart` / `heartFg` 等），
  并注明「健康 / 完成」与「健康（心）」是两套语义 —— 原表只有色值、无 token 名，是本次需靠推断的地方。
- `assets/app_tokens.dart`：同步补 `heartFg`。
  ⚠️ 该模板仍缺项目已落地的 `danger` / `dangerBg` / `dangerText` 三色，属既存漂移，未一并补齐。
- 新增测试：`test/features/memo_page_test.dart`、`test/features/schedule_page_test.dart`
  （含「不渲染设计稿演示内容」的源码守卫，沿用项目既有诚实性断言风格）。
