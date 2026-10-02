# 设计稿对齐 · 待选任务清单（2026-10-02）

来源：`docs/design-alignment-audit-2026-10-02.md`（差异审核报告）。
勾选方式：直接勾 `- [ ]`，或按 ID 告诉我「做 DA-xx」。

**图例** — 改动量：S（≤1 文件/纯文案）· M（单页/单组件）· L（跨页或多组件）
**Golden 影响**：会不会动到既有 golden（影响 = 需 `--update-goldens` 重生成）

---

## ✅ 本轮已完成

- [x] **DA-01 账本页合并为单一「记一笔」** — 两个并列 EntryCard 合并为单入口 + `sync-link` 次级链；补「需要你的确认」块（`LedgerConfirmRow`，确认/修改/忽略按 reason 出招）；`CategoryBar` 改四色轮转；`direction` 枚举转中文。
  **并把「待确认」从 34 移回 31**（`components.md` B11 明确「待确认不在这里」），34 改为纯二级管理页（来源 + 规则），AI 结论改为「拿不准的已放在账本首页等你确认」。
- [x] **DA-02 AiCard 补 ✦ AI 标识行** — 按 `.ai-card .tag`：✦ 13px + 12px/700 aiPrimary，字距 0.72，下间距 9。红线 1。
- [x] **DA-03 抽公共 `SparkleIcon`（✦ 四芒星）** — 新增 `components/sparkle.dart`；替换 `ModeChip` / `MemHint` / `AskPill` / `CaptureBar` / `ProcCard` 的 Material `auto_awesome`；Tab 栏删掉私有 `_SparklePainter` 改用同一组件。
  **顺带清掉全仓剩余 Material 图标**（红线 7）：`rows.dart`、`proc_card.dart`、`privacy_page`、`health_consent`、`health_probe`、`home_page`、`ledger_page` 共 13 处 → Lucide。
- [x] **DA-04 首页（客户端部分）** — 头像由 `Icons.person` 改字母头像（设计稿 `远`）；健康 hint 改读 `health.source`，后端未填则不显示（不编造设备名）。
  ⚠️ **未交付**：周柱状图（`weekBars`）与 `MetricCard` sparkline —— 见 **DA-25**。
- [x] **DA-05 健康页（结构与 IA）** — 按 B6 重排为「**AI 状态解读优先**（红线 4，原先排在最后）→ 睡眠趋势 → 今日指标 → 来源声明」；新增 `InsightHero` 组件（`insightHero` 渐变 + 评分标签）与 `health_repository`（读 `/health/score`）；未授权走诚实空态、不出任何数值；常驻免责保留。
  ⚠️ **未交付**：真实睡眠趋势与指标内容 —— 见 **DA-26**。

## 🚫 有意偏差（已裁决：保留增强，登记偏差）

以下与设计稿不一致但**保留**，不再作为待办：

| ID | 位置 | 偏差 | 保留理由 |
|---|---|---|---|
| DEV-01 | 养车记一笔（36） | 多出 `LedgerPad` 金额键盘（设计无） | 键盘录入体验增强 |
| DEV-02 | 登录页（00） | 多出「上次登录 $email」chip（设计无） | 便利性 |
| DEV-03 | 简报页（11） | 标题由服务端驱动（设计为固定文案「早上好，我整理好了你的今天。」） | 服务端可运营 |
| DEV-04 | 我的页（50） | 「状态异常提醒」用「即将开放」文案代替开关 | M4 门控（健康未接入） |

## P1 · 功能缺口（数据源已在，可直接开工）

- [ ] **DA-06 记一笔「说给亚丝娜 / 键盘输入」双模** — `ledger_add_page.dart`
  缺 seg 切换、say-box + 示例 chip、解析卡「我听到的」。改动量 **L**｜Golden：`ledger_add`
- [ ] **DA-07 对话页消息后建议 chip 行** — `chat_page.dart`
  缺「查看行程 / 调整预算 / 换个人少的目的地」。改动量 **M**｜Golden：无
- [ ] **DA-08 相册批量管理补全** — `album_manage_page.dart`
  缺「全选」、过期截图/相似连拍/手动挑选**分组 + 组标签**、「移动」「加标签」、预选 ai-hint 与回指 62。改动量 **L**｜Golden：无
- [ ] **DA-09 相簿详情补全** — `album_detail_page.dart`
  缺 AI 整理卡、`✦` 连拍原片徽章、批量管理按钮、隐私卡；日期头缺地点/视频段数。改动量 **L**｜Golden：无
- [ ] **DA-10 单张照片补全** — `photo_view_page.dart`
  缺「我留了这张」`✦` 徽章、AI 说明卡 + chip 行、「照片信息」标题、底部 收藏/移到相簿/删除 actionbar。改动量 **L**｜Golden：无
- [ ] **DA-11 AI 整理建议页对齐** — `album_ai_page.dart`：补底部隐私卡、建议行集合。改动量 **M**｜Golden：无
- [ ] **DA-12 车辆页指标与配色** — `car_page.dart`：指标标签改「本月充电 186 kWh / 百公里电耗 / 总里程」；`CategoryBar` 四色；记录行强调色。改动量 **M**｜Golden：`car_page`
- [ ] **DA-14 车辆档案微调** — `car_profile_page.dart`：section hint 文案；补 AiCard 的「看本月养车账 →」。改动量 **S**｜Golden：`car_profile`

## P2 · 文案小差异（低风险）

- [ ] **DA-15 我的页对齐** — `profile_page.dart`：身份行补「· 关系 Lv.N」；「健康数据授权」→「数据授权」+ 副文案；「记忆管理」副文案补条数；「隐私设置」副文案改「本地优先 · 一键清空 · 导出数据」。（「状态异常提醒」按 DEV-04 保留）改动量 **S**｜Golden：无
- [ ] **DA-16 验证码页文案** — `verify_code_page.dart`：隐私文案对齐；重发倒计时去掉多余空格。改动量 **S**｜Golden：无

## P3 · 需产品 / 架构裁决或后端改动

- [ ] **DA-25 首页数据可视化 · 后端契约扩展** — `/home/summary` 需补 `spend.week_bars`（7 日消费序列）与 `health.cells[].spark`（指标 sparkline），端上 `SpendSummary.weekBars` / `MetricCard.sparkValues` 已就绪可直接接。**前置**：后端测试需 DB，本机不可验证
- [ ] **DA-26 健康域真实内容** — 睡眠趋势 7 柱 / 今日指标三行 / 综合评分。**前置**：`PLT-001` 通过、`/health/sync` 真正落库（当前是 no-op 骨架，`authorized` 恒 false）
- [ ] **DA-19 日程「完成态」** — 需 `GET /tasks` 返回已完成任务
- [ ] **DA-20 备忘录「过期清理建议」** — 需过期判定 + 建议数据源
- [ ] **DA-21 对话 · AI 记账 4 步 ProcCard** — 需 `tool_step` 持久化
- [ ] **DA-22 文档修订** — `docs/version/v5.0.0/traceability.md:480` 仍写「生活宫格 3×3 / 日历·旅行后置」，加 2026-09-30 裁决修订注记。改动量 **S**
- [ ] **DA-23 Skill 模板补齐** — `.agents/skills/zhaoxi-design-system/assets/app_tokens.dart` 缺 `danger` / `dangerBg` / `dangerText`。改动量 **S**

## P4 · 本轮新发现（低优先，可择机）

- [ ] **DA-27 账本「最近账单」逐行语义色** — 设计为 餐饮=money / 交通=aiBlue / 购物=aiPrimary，现统一 money。需先定「分类 → 语义色」映射（`categoryId` 是 id 不是名称）。改动量 **M**
- [ ] **DA-28 记一笔图标** — 设计用铅笔，`AppIcons` 无该字形（需 `tool/gen_app_icons.py` + 字体重生成）；现用 `AppIcons.wallet`。改动量 **S**（但需动字体资产）
- [ ] **DA-29 组件测试补 SparkleIcon / InsightHero** — 新组件目前只被页面测试间接覆盖。改动量 **S**

## P5 · 验证（需可用 Flutter 环境）

- [ ] **DA-30 重生成 golden + 全量回归**

  ```bash
  cd apps/mobile
  flutter test --update-goldens     # 见下方清单，建议 regen 后 review diff
  flutter test && flutter analyze
  ```

  **本轮 golden 受影响清单**（渲染已变，必须重生成）：
  - 设计系统：`a2_ai_card`、`a6_task`、`a8_ask_pill`、`a10_mode_chip`、`a11_mem_hint`、`a14_proc`、`a17_capture`、`ledger_entry`
  - **新增**：`ledger_sync_link`（需生成）
  - 功能页：`life_page_modules`、`ledger_auto`、`ledger_auto_no_accuracy`、`ledger_add`、`ledger_page_entry_row`、`car_page`、`car_add`、`car_profile`
  - `a9_tabbar` 预期**不变**（✦ 路径与尺寸一致），若 regen 后无 diff 属正常

  注：本机 Flutter 工具链无法 spawn 子进程（Windows `CreateFile failed 231`），此步需在可用环境执行。
  本轮已用 `dart --disable-dart-dev` + `package:analyzer` 做进程内静态校验：**166 文件 0 error / 0 warning**。

---

## 依赖关系速查

- DA-06 与 DA-01 同属记账域，DA-01 已改入口结构，DA-06 接着改录入页最顺
- DA-02 / DA-03 已改组件层，**所有含 AiCard / CaptureBar / MemHint / ModeChip / AskPill / ProcCard 的 golden 都要重生成**（见 DA-30）
- DA-25 / DA-26 同属「后端契约与健康域」，建议合并推进；DA-26 卡 `PLT-001`
- DA-19 / DA-20 / DA-21 卡后端契约
- DEV-01~04 已裁决保留，不再计入待办
