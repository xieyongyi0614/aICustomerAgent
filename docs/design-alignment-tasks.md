# 设计稿对齐 · 待选任务清单（2026-10-02）

来源：`docs/design-alignment-audit-2026-10-02.md`（差异审核报告）。
勾选方式：直接勾 `- [ ]`，或按 ID 告诉我「做 DA-01、DA-04」。

**图例** — 改动量：S（≤1 文件/纯文案）· M（单页/单组件）· L（跨页或多组件）
**Golden 影响**：会不会动到既有 golden（影响 = 需 `--update-goldens` 重生成）

---

## P0 · 撞 IA 裁决 / 设计红线（建议优先）

- [ ] **DA-01 账本页合并为单一「记一笔」入口** — `features/ledger/presentation/ledger_page.dart`
  现状：`手动记一笔` + `AI 自动记账` 两个并列 EntryCard。
  设计/裁决：**单一「记一笔」（33）** + 同步与规则次级入口；另补「需要你的确认」块；`CategoryBar` 改四色（money/blue/purple/health）。
  依据：`SKILL.md` IA 裁决 2「记账永远单一模块，不得拆两个并列入口」。改动量 **M**｜Golden：`ledger_page_entry_row` 受影响

- [ ] **DA-02 AiCard 补 ✦ AI 标识行** — `design_system/components/cards.dart`
  现状：只渲染标题。设计 `.ai-card .tag` = **✦ + 12px/700 aiPrimary 标签行**。
  依据：红线 1「用户必须一眼分辨哪部分是 AI」。改动量 **S**｜Golden：所有含 AiCard 的页面 golden 受影响（**面较大**）

- [ ] **DA-03 抽公共 `SparkleIcon`（✦ 四芒星）** — 新增组件 + `CaptureBar`/`ModeChip`/`MemHint`
  现状：三处用 Material `Icons.auto_awesome`。tokens.md 要求 AI 相关一律用 ✦ 固定路径（现仅 Tab 栏有私有 `_SparklePainter`）。
  依据：红线 7「图标用 Lucide 不用 Material Icons」。改动量 **M**｜Golden：`a10_mode_chip` / `a11_mem_hint` / `a17_capture` 受影响

## P1 · 功能缺口（数据源已在，可直接开工）

- [ ] **DA-04 首页数据可视化补全** — `features/home/presentation/home_page.dart`
  ① `SpendSummary.weekBars` 现传空数组 → 接真实周数据；② `MetricCard` 加 sparkline；③ 健康 hint 文案；④ 头像改字母头像（去掉 `Icons.person`）。
  改动量 **M**｜Golden：无既有首页 golden

- [ ] **DA-05 健康页内容实现** — `features/health/presentation/health_page.dart`
  现状 **内容桩**：4 个「连接手环后…」空占位。设计要 insight-hero（综合评分 + 叙事）、睡眠趋势 7 柱、今日指标 3 行。
  ⚠️ **前置**：需先确认 `API-009` 健康 ingest 是否已落地；无数据则只能做空态美化。
  依据：红线 8（医疗免责常驻、禁医疗级宣称）。改动量 **L**｜Golden：无

- [ ] **DA-06 记一笔「说给亚丝娜 / 键盘输入」双模** — `ledger_add_page.dart`
  缺 seg 切换、say-box + 示例 chip、解析卡「我听到的」。改动量 **L**｜Golden：`ledger_add` 受影响

- [ ] **DA-07 对话页消息后建议 chip 行** — `chat_page.dart`
  缺「查看行程 / 调整预算 / 换个人少的目的地」。改动量 **M**｜Golden：无

- [ ] **DA-08 相册批量管理补全** — `album_manage_page.dart`
  缺「全选」、过期截图/相似连拍/手动挑选**分组 + 组标签**、「移动」「加标签」动作、预选 ai-hint 与「这些预选是怎么算出来的 →」回指 62。
  改动量 **L**｜Golden：无（album golden 均为组件级）

- [ ] **DA-09 相簿详情补全** — `album_detail_page.dart`
  缺 AI 整理卡、`✦` 连拍原片徽章、批量管理按钮、隐私卡；日期头缺地点 / 视频段数。改动量 **L**｜Golden：无

- [ ] **DA-10 单张照片补全** — `photo_view_page.dart`
  缺「我留了这张」`✦` 徽章、AI 说明卡 + chip 行、「照片信息」标题、底部 收藏/移到相簿/删除 actionbar；信息行字段对齐（拍摄时间/地点/相簿/大小）。改动量 **L**｜Golden：无

- [ ] **DA-11 AI 整理建议页对齐** — `album_ai_page.dart`
  补底部隐私卡；建议行集合对齐（相似连拍本期未开启，需裁决是否保留该行）。改动量 **M**｜Golden：无

- [ ] **DA-12 车辆页指标与配色** — `car_page.dart`
  指标标签改「本月充电 186 kWh / 百公里电耗 / 总里程」；`CategoryBar` 四色；记录行强调色逐行不同。改动量 **M**｜Golden：`car_page` 受影响

- [ ] **DA-13 养车记一笔对齐** — `car_add_page.dart`
  多出 `LedgerPad` 键盘（设计无）；AI 提示改行内 `ai-hint`；区块顺序对齐。
  ⚠️ **需先裁决**：键盘是刻意增强还是偏差？改动量 **M**｜Golden：`car_add` 受影响

- [ ] **DA-14 车辆档案微调** — `car_profile_page.dart`
  section hint 文案；补 AiCard 的「看本月养车账 →」链接。改动量 **S**｜Golden：`car_profile` 受影响

## P2 · 文案 / 视觉小差异（低风险，可批量）

- [ ] **DA-15 我的页对齐** — `profile_page.dart`
  身份行补「· 关系 Lv.N」；「健康数据授权」→「数据授权」+ 副文案；「记忆管理」副文案补条数；「隐私设置」副文案改「本地优先 · 一键清空 · 导出数据」；「状态异常提醒」设计为**开关**（现「即将开放」文案）。
  ⚠️ 开关项受 M4 门控，需裁决是否放开。改动量 **S**｜Golden：无

- [ ] **DA-16 验证码页文案** — `verify_code_page.dart`
  隐私文案对齐；重发倒计时去掉多余空格。改动量 **S**｜Golden：无

- [ ] **DA-17 登录页去掉「上次登录」chip** — `login_page.dart`
  ⚠️ **需裁决**：便利性功能 vs 严格对齐设计稿。改动量 **S**｜Golden：无

- [ ] **DA-18 简报页对齐** — `briefing_page.dart`
  标题改固定文案（现服务端驱动）；「天气按实时定位 · 点按设置」行是否保留。
  ⚠️ 标题服务端驱动是刻意设计，需裁决。改动量 **S**｜Golden：无

## P3 · 需产品 / 架构裁决后才能开工

- [ ] **DA-19 日程「完成态」** — 需 `GET /tasks` 返回已完成任务（现只返未完成），否则设计稿时间线的删除线态永远不出现。后端改动
- [ ] **DA-20 备忘录「过期清理建议」** — 需过期判定 + 建议数据源（现 AI 卡为诚实兜底，不编造）
- [ ] **DA-21 对话 · AI 记账 4 步 ProcCard** — 需 `tool_step` 持久化（代码注释已声明该缺口）
- [ ] **DA-22 文档修订** — `docs/version/v5.0.0/traceability.md:480` 仍写「生活宫格 3×3 / 日历·旅行后置」，加 2026-09-30 裁决修订注记。改动量 **S**
- [ ] **DA-23 Skill 模板补齐** — `.agents/skills/zhaoxi-design-system/assets/app_tokens.dart` 缺 `danger` / `dangerBg` / `dangerText`（项目已落地，模板漂移）。改动量 **S**

## P4 · 验证（需可用 Flutter 环境）

- [ ] **DA-24 重生成 golden + 全量回归**
  ```bash
  cd apps/mobile
  flutter test --update-goldens test/features/life_page_test.dart test/features/ledger_auto_page_test.dart
  flutter test && flutter analyze
  ```
  待重生成：`life_page_modules` / `ledger_auto` / `ledger_auto_no_accuracy`
  注：本机 Flutter 工具链无法 spawn 子进程，此步需在可用环境执行。

---

## 依赖关系速查

- DA-01 与 DA-06 同属记账域，建议同批做（DA-01 改入口结构、DA-06 改录入页）
- DA-02 / DA-03 都会牵动多张 golden，**建议与其他 golden 变更合并成一次 `--update-goldens`**
- DA-05 卡在 `API-009` 健康 ingest 状态；DA-19/20/21 卡在后端契约
- DA-13 / DA-15 / DA-17 / DA-18 需先裁决「刻意增强 vs 偏差」
