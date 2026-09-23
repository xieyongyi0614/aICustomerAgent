# 朝夕 · 设计 Token（定稿）

> 全部值已按 SKILL.md「已裁决的 4 处歧义」定稿。**禁止在代码里写死色值**，一律经 token 取用。
> 真源：`design/ai-life-agent-prototype.html` 的 CSS 变量 + `design/ai-life-agent-design.html` §06。

---

## 1. 色彩

### 1.1 核心 10 项（设计稿 §06 定稿）

| Token | 值 | 语义 | 用途 |
|---|---|---|---|
| `canvas` | `#F5F4F0` | 暖纸白 · 背景 | 全站页面底色 |
| `surface` | `#FFFFFF` | 卡片白 | 所有卡片、气泡、输入丸 |
| `ink` | `#1B1C23` | 墨 · 主文字 | 标题、正文主色 |
| `ink2` | `#6E7079` | 次文字 | 副文案、设置项说明 |
| `ink3` | `#A7A8B1` | 弱文字 | 占位符、提示、单位 |
| `line` | `#ECEAE3` | 分割线 | 卡片内分隔、Tab 上边线 |
| `aiPrimary` | `#7A5CFF` | AI 紫 · 强调 | AI 语义主色、chip、标签 |
| `aiBlue` | `#3E8BFF` | AI 蓝 | AI 次强调、可点链接 |
| `aiCyan` | `#2BD2E8` | AI 青 | AI 渐变终点 |
| `warm` | `#FF9D76` | 暖橙 · 关怀/提醒 | 主动关怀、步数、提醒 |
| `health` | `#33BC8C` | 青绿 · 健康/完成 | 健康、完成态、在线点 |
| `money` | `#EFA63C` | 麦金 · 财务 | 记账、预算、餐饮 |

> ⚠️ 设计稿 `:root` 里的 `#FAF9F6` / `#62646E` / `#9C9DA7` / `#EAE8E1` 是**笔误**，不要使用。

### 1.2 中性补充色（原型在用，设计稿未列）

| Token | 值 | 用途 |
|---|---|---|
| `fillSubtle` | `#F3F2ED` | 任务标签底、次级填充 |
| `fillMuted` | `#F1F0EA` | 「即将上线」图标底 |
| `trackBar` | `#F0EFE9` | 进度条 / 分类条轨道 |
| `borderDashed` | `#DAD9D1` | 虚线占位卡边框 |
| `borderCheck` | `#D7D5CD` | 复选框未选中边框 |
| `toggleOff` | `#DDDCD4` | 开关关闭态 |
| `inkOnSoon` | `#B9B8AF` | 占位卡图标色 |

### 1.3 深色 / 反白场景文字色

| Token | 值 | 场景 |
|---|---|---|
| `onDeepPrimary` | `#FFFFFF` | 深夜紫卡主文字 |
| `onDeepSecondary` | `rgba(255,255,255,.72)` | 深夜紫卡次文字 |
| `onDeepTertiary` | `rgba(255,255,255,.65)` | 简报卡小标题 |
| `bodyOnCard` | `#33343D` | `ai-card` 正文 |
| `bodyOnBubble` | `#2C2D35` | AI 气泡正文 |
| `userBubbleBg` | `#1F222B` | 用户气泡底 |
| `userBubbleText` | `#F4F4F7` | 用户气泡文字 |
| `bodyOnInsight` | `#3A3B45` | 健康 Hero 卡正文 |
| `privacyText` | `#2E7D5F` | 隐私承诺卡文字 |
| `onWhitePill` | `#2B2A3D` | 白底胶囊（简报「开始今天」/ Mode 选中）文字 |
| `avatarText` | `#7A3A1B` | 头像文字 |

### 1.4 语义色底（浅底 + 实色图标）

图标底色方块统一用「同色 12–16% 透明 + 实色图标」：

| 语义 | 底色 | 图标色 |
|---|---|---|
| AI | `rgba(122,92,255,.12)` | `aiPrimary` |
| 健康 / 完成 | `rgba(51,188,140,.12)` | `health` |
| 财务 | `rgba(239,166,60,.14)` | `money` |
| 关怀 / 步数 | `rgba(255,157,118,.16)` | `warm` |
| 信息 / 交通 | `rgba(62,139,255,.12)` | `aiBlue` |
| 旅行 | `rgba(43,210,232,.13)` | `#1FA8BC` |
| 健康（心） | `rgba(255,107,107,.12)` | `#F06A6A` |

### 1.5 记忆类型标签（记忆页专用）

| 类型 | 底色 | 文字色 |
|---|---|---|
| 偏好 | `rgba(122,92,255,.10)` | `aiPrimary` |
| 习惯 | `rgba(239,166,60,.14)` | `#C98418` |
| 目标 | `rgba(51,188,140,.12)` | `#24966E` |
| 关系 / 近况 | `rgba(62,139,255,.12)` | `aiBlue` |

---

## 2. 渐变

### 2.1 AI 渐变（唯一品牌渐变）

```
ai = linear-gradient(135deg, #8B6DFF 0%, #4D8DFF 55%, #2BD2E8 100%)
```

**只用于「AI 的存在与行动」**：Orb、AI 结论卡描边、悬浮对话球、选中态开关、发送键、已完成复选框。

### 2.2 深夜紫三兄弟（**不要合并**）

| Token | 值 | 场景 |
|---|---|---|
| `deepSummary` | `linear-gradient(140deg, #23232E, #33304A 60%, #3E3A63)` | 记账页月度总览卡 |
| `deepPersona` | `linear-gradient(150deg, #23232E, #37335C 65%, #4A4390)` | 我的页 AI 人格卡 |
| `deepBrief` | `linear-gradient(175deg, #191826 0%, #262445 46%, #3B3672 78%, #4A4390 100%)` | 早间简报全屏页背景 |

### 2.3 数据可视化渐变

| Token | 值 | 场景 |
|---|---|---|
| `barMoney` | `linear-gradient(90deg, #EFA63C, #FFD08A)` | 餐饮 / 预算进度 |
| `barBlue` | `linear-gradient(90deg, #3E8BFF, #9CC2FF)` | 交通 |
| `barPurple` | `linear-gradient(90deg, #7A5CFF, #C3B3FF)` | 购物 |
| `barGreen` | `linear-gradient(90deg, #33BC8C, #9FE8CF)` | 娱乐 |
| `spark` | `linear-gradient(180deg, #33BC8C, #9FE8CF)` | 指标迷你卡 sparkline |
| `dayBars` | `linear-gradient(180deg, #F4C066, #F8DCAB)` | 消费周柱状 |
| `hbar` | `linear-gradient(180deg, #6E93FF, #B9CCFF)` | 睡眠趋势柱（今日柱改用 `ai`） |
| `avatar` | `linear-gradient(135deg, #FFD9C2, #FF9D76)` | 用户头像底 |
| `insightHero` | `linear-gradient(150deg, #FFFFFF, #F4F1FF)` | 健康状态 Hero 卡底 |

---

## 3. 圆角

| Token | 值 | 用途 |
|---|---|---|
| `rLg` | `24` | 大卡（AI 结论卡、总览卡、人格卡、设置组） |
| `rMd` | `18` | 中卡（指标卡、模块卡、记忆卡、简报卡、隐私卡） |
| `rSm` | `12` | 小元素（记忆提示条、Mode 选项） |
| `rFull` | `999` | 按钮、输入丸、chip、开关、进度条 |

**图标底色方块圆角 = 边长 ÷ 3（取整）** —— 设计稿未写明，这是原型的隐含规律：

| 边长 | 圆角 | 用例 |
|---|---|---|
| 26 | 8 | 指标迷你卡图标 |
| 32 | 10 | 设置行图标 |
| 36 | 12 | 账单行图标 |
| 38 | 13 | 健康指标行图标 |
| 42 | 14 | 生活模块图标 |

**纯圆形**（`rFull`）：复选框 21、工具步骤图标 20、输入栏图标 34、发送键 38、用户头像 38、我的页头像 54、悬浮对话球 56。

**气泡**：`20`，且**贴底角改为 `6`**（用户泡右下、AI 泡左下）。

---

## 4. 字号与字重

### 4.1 字号阶（原型实测）

| 字号 | 字重 | 用途 |
|---|---|---|
| 32 | 750 | 月度总览金额 |
| 26 | 750 | 简报页 h1、消费速览金额 |
| 25 | 700 | 首页 hero 主文案 |
| 24 | 700 | 页面标题（`h1.pt`） |
| 18 | 700 | 我的页用户名 |
| 17 | 700 | 问候语、健康状态语 |
| 16.5 | 700 | 区块标题、对话页人名 |
| 16 | 700 | 人格卡名字 |
| 15.5 | 700 | 健康指标数值 |
| 14.5 | 550–600 | 正文、任务标题、简报卡主文案 |
| 14 | 600 | 账单标题、健康指标标题、设置项标题 |
| 13.5 | 400 | 副文案、Hero 卡正文 |
| 13 | 400 | `sub` 通用副文案 |
| 12.5 | 600 | chip 按钮、记忆计数 |
| 12 | 600–700 | 标签、记忆提示条 |
| 11.5 | 600–700 | 模式 chip、记忆类型标签、简报卡小标题、设置项说明 |
| 11 | 600–650 | 指标说明、任务标签、健康评分标签 |
| 10.5 | 600–700 | Tab 文字、模块摘要、趋势柱标签、Mode 副标 |

### 4.2 字重档

设计稿定义：标题 700–800、正文 400–550、辅助 400–600。原型实际使用：**400 / 550 / 600 / 650 / 700 / 750**。

> 🚨 **跨端坑**：Flutter 的 `FontWeight` 常量只有 `w100`–`w900`（100 的整数倍），**550 / 650 / 750 无法直接表达**。
> - 若用**可变字体**：`FontVariation('wght', 550)` 可精确还原。
> - 若用**系统字体**（非可变）：必须降级映射 —— `550 → w500`、`650 → w600`、`750 → w700`。
> 选定方案后在 `AppTypography` 里统一封装，**禁止在页面里直接写 `FontWeight.w550`**（编译不过）或随手挑一个近似值。

### 4.3 字体族

```
-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC",
"HarmonicOS Sans SC", "Microsoft YaHei", sans-serif
```

- **数字必须等宽**：`fontFeatures: [FontFeature.tabularFigures()]`。否则金额滚动时左右跳动。
- 大号金额加 `letter-spacing: -0.02em`；标题加 `-0.01em`。

---

## 5. 投影

| Token | 值 | 用途 |
|---|---|---|
| `shadowCard` | `0 10px 30px rgba(27,28,35,.06)` | **所有卡片**（唯一常规投影） |
| `shadowDeep` | `0 16px 36px rgba(30,28,55,.35)` | 深夜紫卡（总览卡 / 人格卡） |
| `orbGlow` | `0 10px 30px rgba(102,90,255,.45), 0 0 60px rgba(63,150,255,.35), inset 0 0 0 1px rgba(255,255,255,.5)` | AI 核心球 |
| `orbBtnShadow` | `0 10px 24px rgba(102,90,255,.45), 0 0 0 6px rgba(245,244,240,.9)` | 悬浮对话球（外圈 6px 与背景同色，形成挖空感） |

> 常规 UI 只有**一档**投影。多档投影会让界面「脏」。

---

## 6. 间距

| Token | 值 | 用途 |
|---|---|---|
| `pageH` | `18` | 页面左右内边距 |
| `cardPadding` | `18` | 大卡内边距 |
| `cardPaddingSm` | `13–16` | 中/小卡内边距 |
| `listCardPadding` | `6 / 18` | 列表型卡片（上下 6、左右 18） |
| `gapCard` | `11–14` | 卡片之间 |
| `gapGrid` | `10–11` | 宫格间隙 |
| `gapSection` | `24` | 段落区间隔 |

**屏幕级**：

| 项 | 值 |
|---|---|
| 屏幕内边距 | `top 60 / sides 18 / bottom 118`（顶部让开状态栏，底部让开 Tab 栏） |
| 状态栏高 | `48` |
| Tab 栏高 | `88` |
| 对话页输入栏 | `bottom 88`（在 Tab 栏之上） |
| 参考设备 | `390 × 844`（原型手机壳尺寸） |

---

## 7. 动效

| Token | 值 | 用途 |
|---|---|---|
| `pageTransition` | `0.38s cubic-bezier(.22,.9,.3,1)`，`opacity 0→1` + `translateY 14px→0` | 页面切换 |
| `orbBreathe` | `4.2s ease-in-out infinite`，`scale 1 → 1.055` | Orb 呼吸（**唯一例外，不受 400ms 限制**） |
| `orbSwirl` | `7s linear infinite`，`rotate 0→360deg` | Orb 内层色相流动 |
| `spin` | `0.9s linear infinite` | 工具步骤当前步旋转、思考中 |
| `typing` | `1.1s infinite`，三点延迟 `0 / .18 / .36s`，`opacity .35→1` + `translateY 0→-3px` | 输入指示器 |
| `pressScale` | `0.15s`，`scale 1 → .96` | 模块卡按压反馈 |

> **纪律：除 Orb 与循环指示器外，所有动效 ≤ 400ms，无弹跳滥用。**

---

## 8. 图标

- **风格**：Lucide 线性，`stroke-width: 2`，`stroke-linecap: round`，圆角端点。
- **禁用**：Material Icons、实心填充图标（AI 四芒星除外）。
- **尺寸**：`15 / 16 / 17 / 18 / 20 / 23 / 24`（按场景；Tab 栏 23、卡片标题 15、行内 16–18）。
- **AI 语义符号 = ✦ 四芒星**，路径固定：
  ```
  M12 2l2.4 7.2L22 12l-7.6 2.8L12 22l-2.4-7.2L2 12l7.6-2.8z
  ```
  用于：AI 结论卡标题、记忆提示条、模式 chip、悬浮对话球、AI 头像旁、加载占位。
- **承载方式**：功能色**浅底圆角方块**（见 §1.4）+ 实色图标，圆角 = 边长 ÷ 3。

---

## 9. 无障碍与对比度

| 组合 | 对比度 | 判定 |
|---|---|---|
| `ink` on `canvas` | 约 15:1 | ✅ 远超 AA |
| `ink2` on `canvas` | 约 4.6:1 | ✅ 达 AA |
| `ink3` on `canvas` | 约 2.4:1 | ⚠️ **仅可用于装饰性文字与单位**，不可承载关键信息 |
| `aiPrimary` on `canvas` | 约 4.3:1 | ⚠️ 临界，正文不要用，仅用于标签/图标 |
| `onWhitePill` on `#FFFFFF` | 约 12:1 | ✅ |

**要求**：支持系统字号放大至 200% 不破版；Orb 必须有语义标签（`Semantics(label: '亚丝娜，AI 助手')`）。
