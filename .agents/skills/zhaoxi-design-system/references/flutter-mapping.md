# Flutter 落地映射

> 色值 / 尺寸的具体数值见 `tokens.md`，本文件只讲**怎么落到 Flutter**。可直接拷用的模板见 `../assets/app_tokens.dart`。

---

## 1. Material 3 的五条禁令

**前提**：朝夕的设计语言**不是 Material**（暖纸白底、圆角 18–24、Lucide 图标、渐变描边卡、AI 语义渐变、Orb 本体）。而 M3 自带一整套视觉主张（tonal palette、`surfaceTint` 色渗、`NavigationBar` 的 pill indicator、默认 `TextTheme` 阶）。**直接开 M3，页面会「看起来像安卓自带 App」**，与「温暖而非企业」正面冲突。

**结论：保留 M3 的交互与无障碍底座，剥掉它的视觉主张。**

| # | 禁令 | 原因 |
|---|---|---|
| 1 | **不用 `ColorScheme.fromSeed`** | 它会从种子色推导整套 tonal palette，与 10 个固定 token 直接打架。改为**手工构造 `ColorScheme`**，把设计 token 显式映射进去 |
| 2 | **不用 M3 默认 `TextTheme`** | M3 的 display / headline / title 阶与朝夕的 6 级字号阶不对应。必须用朝夕字号阶覆盖 |
| 3 | **显式关闭 `surfaceTintColor` 与默认 elevation** | 否则 `Card` / `ElevatedButton` 会带 M3 色渗与 tonal elevation，视觉上「脏」 |
| 4 | **图标用 Lucide，不用 Material Icons** | 设计稿明确要求「Lucide 风格 2px 线性圆角」；AI 相关一律 ✦ 四芒星 |
| 5 | **Tab 栏自绘** | 朝夕的 Tab 是「4 个位置、中间是悬浮球」的特殊形态，M3 `NavigationBar` 无法表达 |

**保留 M3 的部分（这些是白拿的）**：`InkWell` 水波纹与手势、`Focus` / 键盘导航、语义标签（TalkBack / VoiceOver）、页面转场、`MediaQuery` 文本缩放适配、`Scaffold` / `SafeArea` 插边处理。

> ⚠️ `app/theme/` 必须是一个**显式的覆盖层**（把 M3 默认值逐项关掉），而不是 `ThemeData(useMaterial3: true)` 一行了事。

---

## 2. ThemeExtension 结构

`AppColors` **必须是 `ThemeExtension`**，不能是 `static const` —— 因为要支持深色模式对调（见 §5）。

```
AppTheme (ThemeExtension × 6)
├── AppColors     核心 10 项 + 中性补充 + 深色场景文字色 + 语义浅底
├── AppGradients  ai / deepSummary / deepPersona / deepBrief / 数据可视化渐变
├── AppRadii      rLg 24 / rMd 18 / rSm 12 / rFull 999 + iconTile(size)
├── AppTypography 6 级字号阶 + 字重 + 数字等宽变体
├── AppElevation  shadowCard / shadowDeep / orbGlow / orbBtnShadow
├── AppSpacing    pageH 18 / card 18 / gapCard 12 / gapSection 24 + 屏幕级常量
└── AppMotion     pageTransition 380ms / orbBreathe 4200ms / orbSwirl 7000ms / spin 900ms
```

**取用方式**：`Theme.of(context).extension<AppColors>()!`。建议在 `app/theme/` 里包一层 `context.colors` / `context.gradients` 扩展方法，避免页面里写长串。

**图标方块圆角**用函数表达，别写死：

```dart
// 规则：边长 ÷ 3（取整）
double iconTile(double size) => (size / 3).roundToDouble();
// 26→8  32→10  36→12  38→13  42→14
```

---

## 3. 四处无法 1:1 平移的视觉点

### 3.1 AI 结论卡 1.5px 渐变描边

- **问题**：`Container.decoration.border` **不支持渐变**（只有纯色 `BorderSide`）。
- **做法**：自绘 —— 先按 `RRect`（圆角 24）用 `Paint()..style = stroke..strokeWidth = 1.5..shader = gradient.createShader(rect)` 画描边，再让子内容内缩 1.5px 覆盖白底。
- **不要用 `ShaderMask`**：它会把子内容一起着色，需额外反遮罩，成本更高。
- 描边不透明度 `.55`（**必须**，全不透明度会太抢）。

### 3.2 Orb 内层高光的 `mix-blend-mode: screen`

- **问题**：CSS 的 `mix-blend-mode` 在 Flutter 无直接对应。
- **做法**：`Canvas.saveLayer(bounds, Paint())` → 画底层径向渐变 → 第二层起用 `Paint()..blendMode = BlendMode.screen` 画两层高光 → `restore()`。
- **注意**：`saveLayer` 开销大，**必须**包 `RepaintBoundary`，且只在可见时开动画。详见 `orb.md` §5。

### 3.3 字体族

- **问题**：Android 无 PingFang SC。
- **做法**：iOS 用系统 `PingFang SC`（不打包）；Android 用 `HarmonyOS Sans SC` 或思源黑体（**需确认授权后打包**），回退 `sans-serif`。
- 字体资源不进仓库（体积 + 授权），由构建期拉取。
- **未落实前先用系统默认字体跑通全流程** —— 字体只影响 token 层，不阻塞开发。

### 3.4 数字等宽

- **问题**：默认数字是比例字形，金额滚动时左右跳动。
- **做法**：所有数值型 `TextStyle` 统一加 `fontFeatures: [FontFeature.tabularFigures()]`，封装成 `AppTypography.numeric` 变体。
- **禁止在页面上手写数字样式**（必然漏）。账本金额、指标卡、进度环全部走它。

### 3.5 ⚠️ 额外坑：字重 550 / 650 / 750

`tokens.md` §4.2 指出原型大量使用 **550 / 650 / 750**，而 Flutter 的 `FontWeight` 常量只有 `w100`–`w900`（100 整数倍）。

| 方案 | 做法 | 取舍 |
|---|---|---|
| A（推荐，可变字体） | `fontVariations: [FontVariation('wght', 550)]` | 精确还原；需引入可变字体 |
| B（系统字体） | 降级映射 `550→w500`、`650→w600`、`750→w700` | 零成本；粗细略平 |

**选定后在 `AppTypography` 里统一封装**，禁止在页面里随手挑近似值。

---

## 4. 状态与架构（与本设计系统相关的部分）

| 关注点 | 约定 |
|---|---|
| 主题获取 | `Theme.of(context).extension<AppX>()`，不直接 import 常量 |
| 设计系统目录 | `lib/design_system/{tokens,components,orb}/` |
| 组件归属 | 设计系统组件**不得** import `core/` 或 `features/`（必须能脱离网络与业务独立渲染，才能做 golden 测试） |
| Orb 的 controller | 用 `useAnimationController`（hooks 的合规用法） |
| 状态 | 设计系统组件全部无状态；状态由上层注入 |

---

## 5. 深色模式

设计稿 §09 明确要求 token 支持**暖纸白 ↔ 深夜紫对调**。

| token | 浅色 | 深色（对调后） |
|---|---|---|
| `canvas` | `#F5F4F0` | `#191826` |
| `surface` | `#FFFFFF` | `#262445` |
| `ink` | `#1B1C23` | `#F4F4F7` |
| `ink2` | `#6E7079` | `rgba(255,255,255,.72)` |
| `ink3` | `#A7A8B1` | `rgba(255,255,255,.55)` |
| `line` | `#ECEAE3` | `rgba(255,255,255,.12)` |
| `shadowCard` | `0 10px 30px rgba(27,28,35,.06)` | `0 10px 30px rgba(0,0,0,.35)` |

> **深色模式是 V1.1 范围**，但 token 结构**必须**从一开始就支持对调（这就是 `AppColors` 必须做成 `ThemeExtension` 的原因）。若一开始写成 `static const`，后期改造会波及所有页面。

---

## 6. 交付前自检

- [ ] 全仓 grep 无硬编码色值（`Color(0x` / `Colors.` 只允许出现在 `app_tokens.dart`）
- [ ] 与设计稿截图比对，无 M3 默认视觉特征（色渗 / pill indicator / 字号阶偏移）
- [ ] 渐变描边只出现在 `ai-card`
- [ ] Tab 栏是自绘的，中间悬浮球是 56px 线性渐变球（**不是 Orb**）
- [ ] 数字样式全部走 `AppTypography.numeric`
- [ ] Orb 包了 `RepaintBoundary` + `TickerMode`
- [ ] `flutter analyze` 干净（尤其检查 `FontWeight.w550` 这类不存在的常量）
