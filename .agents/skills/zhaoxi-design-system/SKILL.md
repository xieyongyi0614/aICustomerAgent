---
name: zhaoxi-design-system
description: 朝夕（Zhaoxi）AI Personal Life Agent 的设计系统唯一真源。当任务涉及朝夕 App / 个人生活智能体的界面设计、样式实现、组件开发、设计稿产出、视觉评审、Flutter 主题与 token、HTML 高保真原型、色彩/字体/圆角/投影/动效规范、AI 核心球（Orb）视觉，或需要判断某个界面「像不像朝夕」时，都应使用本 skill。产出或修改任何朝夕相关 UI 之前必须先读本 skill。
metadata:
  author: zhaoxi-project
  version: "1.0"
  source: design/pages/（按页拆分原型，现役）+ design/ai-life-agent-design.html（产品设计稿；ai-life-agent-prototype.html 已冻结存档）
agent_created: true
---

# 朝夕设计系统

## 用途

为「朝夕 · AI Personal Life Agent」提供**唯一的视觉与交互真源**。任何朝夕相关的界面产出（Flutter 主题、页面组件、HTML 原型、设计稿、视觉评审）都必须以本 skill 为准，不得凭个人审美另起一套。

## 何时使用

- 实现或修改朝夕 App 的任何页面、组件、样式
- 新建或调整 Flutter 主题层（`ThemeExtension` / `ColorScheme` / `TextTheme`）
- 产出朝夕的 HTML 高保真原型、设计稿、视觉说明
- 评审现有界面是否「像朝夕」（视觉走查）
- 需要朝夕的色值、字号、圆角、投影、动效、图标、间距、文案语气

## 真源与优先级

| 层级 | 文件 | 说明 |
|---|---|---|
| 1（最高） | 本 skill | 已裁决的定稿规范；**与下游冲突时以本 skill 为准** |
| 2 | `design/pages/`（总览 `pages/index.html`） | **现役维护**的按页拆分原型（22 页，每页一个零依赖 HTML）；组件结构与真实文案的真源。新增 / 修改页面只改这里 |
| 3 | `design/ai-life-agent-design.html` | 产品设计稿；§06 视觉规范是色值真源 |

> `design/ai-life-agent-prototype.html`（拆分前的单文件原型）**已冻结，不再维护**：仅为历史对照存档，不随页面演进同步更新；内容是 pages/ 拆分时的同源快照，与现役页面冲突时以 pages/ 为准。

**已裁决的 4 处歧义（不要再翻旧稿重新判断）**：

1. **色值**以设计稿 §06 色卡 + 拆分原型（`design/pages/`）为准。设计稿 `:root` 的 `#FAF9F6` / `#62646E` / `#9C9DA7` / `#EAE8E1` 视为笔误，正确值为 `#F5F4F0` / `#6E7079` / `#A7A8B1` / `#ECEAE3`。
2. **Orb 呼吸时长取 4.2s**（设计稿 §04+ 写的 4s 不采用）。
3. **深夜紫有 3 个不同渐变**（月度总览卡 / 人格卡 / 简报页背景），不要合并成一个。
4. **图标底色方块圆角 = 边长 ÷ 3**（取整）—— 这是原型的隐含规律，设计稿未写明。

## 红线（违反即视为实现缺陷）

1. **AI 渐变只用于「AI 的存在与行动」**。普通 UI 一律中性色。用户必须一眼分辨「哪部分是 AI」。
2. **禁止散落硬编码色值**。所有颜色经 token 取用（Flutter 侧走 `ThemeExtension`）。
3. **卡片即结论**：一卡 = 一个 AI 结论 + 最少支撑数据。禁止 Dashboard 式表格堆叠，禁止纯数据页。
4. **AI 叙事优先**：每页先讲「AI 帮你理解了什么」，再展示原始数据。首屏必须存在 AI 结论块，且**位于原始数据之前**。
5. **圆角 18–24、暖纸白底、柔和投影**。禁止后台系统式的冷灰蓝与密集边框。
6. **动效全部 ≤ 400ms**，无弹跳滥用。唯一例外是 Orb 呼吸（4.2s 循环）。
7. **Material 3 只当底座，不当皮肤**。禁止 `ColorScheme.fromSeed`、禁止 M3 默认 `TextTheme`、必须关闭 `surfaceTint` 与默认 elevation、图标用 Lucide 不用 Material Icons、Tab 栏自绘。详见 `references/flutter-mapping.md`。
8. **医疗免责常驻**：涉及健康数据的任何界面必须带「非医疗建议」表述，且**不得**宣称医疗级血压 / 血糖 / 血氧诊断能力。
9. **相册仅本地**：涉及相册的任何界面必须明示「仅本机存储、不上传服务器」；AI 整理（分类 / 清理建议）必须注明「本机分析」；批量删除必须给出可恢复口径（「最近删除」30 天）。**禁止**出现云同步、云端相册类表述。

## 使用流程

1. **先读 token**：`references/tokens.md` 取全部定稿值（色彩 / 渐变 / 圆角 / 字号 / 投影 / 间距 / 动效 / 图标）。
2. **再读组件规格**：`references/components.md` 取组件尺寸、内边距、层级与真实文案。
3. **涉及 AI 本体时**：读 `references/orb.md`（四态、尺寸档、渲染层、性能要求）。
4. **判断「像不像」时**：读 `references/principles.md`（5 条原则的可判定验收规则 + 反范围 + 文案语气）。
5. **落地 Flutter 时**：读 `references/flutter-mapping.md`（M3 边界 + 映射 + 4 处无法 1:1 平移的替代方案）；模板见 `assets/app_tokens.dart`。
6. **产出后自检**：对照上面「红线」逐条过。任何一条不通过就重做，不要交付。

## 参考文件索引

| 文件 | 内容 |
|---|---|
| `references/tokens.md` | 色彩 10 项 + 3 组渐变 + 圆角 4 档 + 图标方块圆角规则 + 字号 6 级 + 投影 2 档 + 间距标尺 + 动效时长 + 图标规范 |
| `references/components.md` | 38 个组件条目（含记账录入 / AI 自动记账 / 车辆 / 相册族）与真实文案；19 个页面的结构与信息层级 |
| `references/orb.md` | AI 核心球：四态语义、4 个尺寸档、渲染层、性能与功耗要求 |
| `references/principles.md` | 5 条设计原则的可判定验收规则 + 反范围清单 + 文案语气与占位文案 |
| `references/flutter-mapping.md` | M3 五条禁令 + `ThemeExtension` 结构 + 4 处平移替代方案 + 深色模式 |
| `assets/app_tokens.dart` | 可直接拷入工程的 token 模板（首次使用需过一遍 `flutter analyze`） |
| `design/flutter/zhaoxi_orb.dart` | Orb 的 Flutter 完整实现（四态、零依赖、含集成指南注释），可直接拷入工程或交给其他 AI 复用 |

## 常见错误

- 用 `ColorScheme.fromSeed` 生成配色 → 会推导出整套 tonal palette，与 10 个固定 token 打架。
- 把「暖纸白」写成 `#FAF9F6` → 那是设计稿 `:root` 的笔误值，正确是 `#F5F4F0`。
- 给普通卡片加 AI 渐变描边 → 渐变描边**只属于 AI 结论卡**（`ai-card`）。
- 用 Material Icons → 必须 Lucide 2px 线性圆角；AI 相关一律 ✦ 四芒星。
- 数字不加等宽特性 → 金额滚动时会左右跳动，必须 `FontFeature.tabularFigures()`。
- 页面首屏先摆数据再放结论 → 违反「AI 叙事优先」，顺序必须反过来。
- 把「温暖」理解成加装饰 → 温暖来自**留白、圆角、暖底色与语气**，不是加渐变和阴影。
