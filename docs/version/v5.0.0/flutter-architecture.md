# V5.0.0 朝夕 App —— Flutter 端技术方案

> **上游**：`docs/version/v5.0.0/requirements-analysis.md`（需求与缺口，**11 条决策已全部拍定**）、`docs/version/v5.0.0/tasks.md`（41 个任务 / 5 个里程碑）、`docs/version/v5.0.0/traceability.md`（设计稿 119 条要求的覆盖矩阵）。
> **范围**：仅客户端（`apps/mobile/`）。后端方案见 `tasks.md` 的 `API-*` 任务。
> **工程位置**：新建 `apps/mobile/`，**不复用** `apps/frontend/`（React 调试控制台，定位不同）。

---

## 1. 选型

> **已确认栈（你指定）**：Flutter + Riverpod + GoRouter + Dio + Freezed + Drift(SQLite) + Flutter Hooks + Material 3。
> **评估结论**：**7 项无异议，3 项需加约束**（Freezed 主用途、Hooks 用法边界、Material 3 皮肤禁令），**另需补齐 10 项**。

### 1.1 逐项评估

| 关注点 | 选型 | 评估 | 约束 / 说明 |
|---|---|---|---|
| 框架 | Flutter | ✅ 无异议 | — |
| 状态管理 | Riverpod | ✅ 无异议 | 配 `riverpod_generator`；`AsyncValue` 天然三态，对齐设计系统的加载/空/错规范 |
| 路由 | GoRouter | ✅ 无异议 | 声明式 + 深链；原型 `#hash` 可 1:1 映射 |
| 网络 | Dio | ✅ 无异议 | `ResponseType.stream` + `CancelToken` + 拦截器；NDJSON 用 `LineSplitter` 逐行解析 |
| 代码生成 | Freezed | ✅ 接受，但**主用途要换** | 见 §1.2：**最大价值不是给 DTO 生成 `copyWith`，而是给 NDJSON 异构事件建 union** |
| 本地库 | Drift (SQLite) | ✅ 无异议 | 客户端缓存**只存服务端 DTO 投影**，不做本地业务逻辑（降低与后端 Schema 演进的耦合） |
| 局部状态 | Flutter Hooks | ⚠️ **有条件接受** | 见 §1.3：只允许承载 widget 级**临时资源**；业务状态一律 Riverpod |
| 设计底座 | Material 3 | ⚠️ **当底座，不当皮肤** | 见 §1.4：5 条禁令，否则 M3 的视觉主张会污染设计稿 |

### 1.2 Freezed 的真正用武之地：给流式事件建 union

后端 `POST /chat/message` 返回的是**异构 NDJSON 事件流**（`turn_meta` / `token` / `done` / 新增的 `tool_step` / 错误），每行 `type` 不同、字段不同。这是 Freezed 在本项目最有价值的落点：

```text
@freezed
sealed class ChatEvent {
  TurnMeta(...)    // type == "turn_meta"
  TokenDelta(...)  // type == "token"
  ToolStep(...)    // type == "tool_step"（API-002 新增）
  Done(...)        // type == "done"
  Failure(...)     // {detail, error}
}
```

配合 Dart 3 的 `switch` 穷尽检查 → **后端新增事件类型时，客户端在编译期就报错**，而不是运行时静默忽略。这正好补上后端 `EXPECTED_EVENT_TYPES` fail-closed 纪律的**客户端对侧**。

> ⚠️ **Freezed 3.x 语法已变**（改为 `sealed class` + `abstract class X with _$X` 风格），网上大量 2.x 示例会编译不过。锁定版本，并在 APP-001 统一。

**反向建议**：普通 DTO（账本条目、记忆条目）**不必**都上 Freezed。Dart 3 原生 `final class` + 手写 `copyWith` 约 5 行就够，能省掉一批 `.freezed.dart` 的构建时间与心智负担。**只在「需要 union / 需要深度相等 / 需要 JSON」三者之一成立时才用 Freezed。**

### 1.3 Flutter Hooks 的用法边界

`flutter_hooks` 与 Riverpod 同源（Remi Rousselet），用 `hooks_riverpod` 的 `HookConsumerWidget` 组合是**官方支持**的，不冲突。但它引入第二套局部状态心智模型，因此定三条边界：

| 允许 | 禁止 |
|---|---|
| `useAnimationController`（Orb 的呼吸 / swirl 两个 controller —— 这正是 hooks 最舒服的场景） | 用 `useState` 存业务状态（一律走 Riverpod） |
| `useTextEditingController`（对话输入栏） | 用 `useEffect` 做数据拉取（一律走 Riverpod provider） |
| `useDebounce` / `useThrottle`（流式渲染节流、输入联想） | 同一个 widget 里混用 `StatefulWidget` 与 hooks（二选一，不混） |
| `useMemoized`（昂贵的 `Path` / `Shader` 缓存） | 把业务逻辑塞进自定义 hook（hooks 只做资源生命周期，不做领域逻辑） |

> 落地：`design_system/orb/` 与对话输入栏用 hooks；其余一律 `ConsumerWidget`。

### 1.4 Material 3 的五条禁令（本栈最需要认真对待的一条）

**问题**：设计稿的设计语言**不是 Material**——暖纸白底、圆角 18–24、Lucide 2px 线性图标、渐变描边卡、AI 语义渐变、Orb 本体。而 Material 3 自带一整套视觉主张（tonal palette、`surfaceTint` 色渗、`NavigationBar` 的 pill indicator、默认 `TextTheme` 阶）。**直接开 M3，页面会「看起来像安卓自带 App」**，与「温暖而非企业」的设计原则正面冲突。

**结论**：**保留 M3 的交互与无障碍底座，剥掉它的视觉主张。**

| # | 禁令 | 原因 |
|---|---|---|
| 1 | **不用 `ColorScheme.fromSeed`** | 它会从种子色推导整套 tonal palette，与设计稿 10 个固定 token 直接打架。改为**手工构造 `ColorScheme`**，把设计 token 显式映射进去 |
| 2 | **不用 M3 默认 `TextTheme`** | M3 的 display / headline / title 阶与设计稿的 6 级字号（24–28 / 14–15 / 11–13）不对应。用设计稿字号阶覆盖 |
| 3 | **显式关闭 `surfaceTintColor` 与默认 elevation** | 否则 `Card` / `ElevatedButton` 会带 M3 色渗与 tonal elevation，视觉上「脏」 |
| 4 | **图标不用 Material Icons，用 Lucide** | 设计稿明确要求「Lucide 风格 2px 线性圆角」；AI 相关一律 ✦ 四芒星 |
| 5 | **Tab 栏自绘** | 设计稿的 Tab 是「5 个位置、中间是悬浮 Orb 球」的特殊形态，M3 `NavigationBar` 无法表达 |

**保留 M3 的部分（这些是白拿的）**：`InkWell` 水波纹与手势、`Focus` / 键盘导航、语义标签（TalkBack / VoiceOver）、页面转场、`MediaQuery` 文本缩放适配、`Scaffold` / `SafeArea` 插边处理。

> ⚠️ 落地要求：`app/theme/` 必须是一个**显式的覆盖层**（把 M3 默认值逐项关掉），而不是 `ThemeData(useMaterial3: true)` 一行了事。
> **APP-002 的验收要加一条**：与设计稿截图比对，**不得出现 M3 默认视觉特征**（色渗、pill indicator、默认字号阶）。

### 1.5 必须补齐的 10 项（你的清单里没有）

| # | 包 | 用途 | 不补的后果 |
|---|---|---|---|
| 1 | **`flutter_secure_storage`** | 令牌存 Keychain / Keystore | **安全硬缺口**。Dio 不存凭据；Drift 与 `shared_preferences` 都是明文，禁止存令牌 |
| 2 | **`flutter_local_notifications` + `timezone`** | 08:00 早间简报、21:30 晚间总结 | 「主动但克制」的核心卖点退化为 App 内入口（决策 D4 选的就是本地通知） |
| 3 | **`health`** | Health Connect / HealthKit 读取 | 健康模块无法接入（调研确认的合规主路径） |
| 4 | **`permission_handler`** | 通知 / 健康 / 相册权限流 | 权限被拒时无引导路径 |
| 5 | **`fl_chart`** | 睡眠 7 日趋势柱状图 | 趋势图需全自绘（sparkline 与进度条仍建议自绘，更轻更可控） |
| 6 | **`lucide_icons`** | 设计稿指定的图标风格 | 与视觉规范不符（禁令 4） |
| 7 | **`intl` + `flutter_localizations`** | 「¥3,420」「7h12m」「9月23日 周二」格式化 | 日期 / 金额 / 时长格式全手写，易错且难统一 |
| 8 | **Markdown 渲染包**（`flutter_markdown` 或 `markdown` + 自绘） | 对话正文是 Markdown，且**流式** | 需自建解析器。选型时「流式增量渲染」是核心诉求（见 §3.2） |
| 9 | **`mocktail` + `matchesGoldenFile`** | 单元 / golden 测试 | 无法做视觉回归（PLT-004） |
| 10 | **`shared_preferences`** | 非敏感偏好（主动关怀开关、上次会话） | 用 Drift 存这类键值属过度设计 |

> 另：`json_serializable` 会**随 Freezed 一起进来**（Freezed 依赖它做 JSON），不必单独列。

### 1.6 这套栈的真实成本：build_runner 三生成器

**这是引入 Freezed + Drift + `riverpod_generator` 后最容易被低估的成本**：

| 生成器 | 产出 | 触发时机 |
|---|---|---|
| `freezed` + `json_serializable` | `*.freezed.dart` / `*.g.dart` | 改模型 |
| `drift` | `*.g.dart`（表 / DAO） | 改表结构 |
| `riverpod_generator` | `*.g.dart`（provider） | 改 provider |

三个生成器**共用一次 build_runner**：

- **首次全量生成慢**（分钟级），**增量**每次几秒；
- 日常开发必须开 `dart run build_runner watch`，否则改完模型忘记生成会报一堆找不到 `_$Xxx` 的错；
- **冲突风险**：三者都往 `*.g.dart` 写，同一文件被两个生成器处理会互相清空 → **约定：一个文件只被一个生成器处理**（Freezed 模型文件不放 drift 表；drift 表文件不放 Freezed 模型）。

**缓解措施（写进 APP-001）**：

1. `build.yaml` 里给 drift 与 freezed 指定**不同的输出后缀**（如 drift 用 `.drift.dart`），从根上避免覆盖；
2. 生成产物纳入 CI 校验（`build_runner build` 后 `git diff --exit-code`，防止有人改了模型没提交生成物）；
3. `.gitignore` 取舍：生成物**建议提交**（单人开发，省掉每次 checkout 后的生成等待），代价是 diff 变大。

### 1.7 依赖清单（全量 20 项，版本在 APP-001 冻结）

> **版本号不在本方案里钉死**——Flutter 生态迭代快，写死在文档里一个月就过期。**版本由 `APP-001` 用 `flutter pub add` 一次性拉取并提交 `pubspec.lock`**；本节只冻结**包清单与用途**。

| # | 包 | 来源 | 用途 |
|---|---|---|---|
| 1 | `flutter_riverpod` | 你指定 | 状态管理 |
| 2 | `riverpod_annotation` + `riverpod_generator` | 你指定 | provider 代码生成 |
| 3 | `go_router` | 你指定 | 路由与深链 |
| 4 | `dio` | 你指定 | 网络与流式响应 |
| 5 | `freezed` + `freezed_annotation` | 你指定 | 不可变模型 + **流式事件 union**（§1.2） |
| 6 | `json_annotation` + `json_serializable` | 随 Freezed | JSON 序列化 |
| 7 | `drift` + `drift_dev` + `sqlite3_flutter_libs` | 你指定 | 本地结构化缓存 |
| 8 | `flutter_hooks` + `hooks_riverpod` | 你指定 | widget 级临时资源（边界见 §1.3） |
| 9 | `flutter_secure_storage` | **补齐 ①** | 令牌存 Keychain / Keystore |
| 10 | `flutter_local_notifications` + `timezone` | **补齐 ②** | 早间简报 / 晚间总结本地通知 |
| 11 | `health` | **补齐 ③** | Health Connect / HealthKit |
| 12 | `permission_handler` | **补齐 ④** | 权限流 |
| 12a | `geolocator` | **补齐 ⑪**（APP-018 扩展，用户裁决 2026-09-29） | 简报天气端侧实时定位（`features/briefing/data/location_service.dart`）；失败一律返回 null 走服务端兜底链，不新增权限包（复用系统弹窗 + Manifest 声明） |
| 13 | `fl_chart` | **补齐 ⑤** | 睡眠 7 日趋势柱状图 |
| 14 | `lucide_icons` | **补齐 ⑥** | 设计稿指定图标风格 |
| 15 | `intl` + `flutter_localizations` | **补齐 ⑦** | 金额 / 时长 / 日期格式化 |
| 16 | Markdown 渲染包（`flutter_markdown` 或 `markdown` + 自绘） | **补齐 ⑧** | 对话正文（流式，注意 §3.2 的增量渲染要求） |
| 17 | `mocktail` | **补齐 ⑨** | 单元测试替身 |
| 18 | `shared_preferences` | **补齐 ⑩** | 非敏感偏好 |
| 19 | `build_runner` | 构建期 | 三生成器宿主 |
| 20 | `flutter_lints` | 构建期 | lint 基线 |

**明确不引入**（避免后续误加）：

| 包 | 否决理由 |
|---|---|
| `get` / `getx` | 与 Riverpod 职责重叠，且隐式依赖 `BuildContext` |
| `bloc` / `flutter_bloc` | 对本产品多数页面属过度设计（§1.1） |
| `isar` / `hive` | 已有 Drift；多引一套本地库只增加迁移负担 |
| `provider` | 无编译期安全，能力被 Riverpod 覆盖 |
| `dynamic_color` 等 M3 主题包 | 与「M3 当底座不当皮肤」正面冲突（§1.4 禁令 1） |

---

## 2. 工程分层与目录结构

```text
apps/mobile/
├── lib/
│   ├── main.dart
│   ├── app/                     # 装配层：只做组装，不含业务
│   │   ├── bootstrap.dart       # 启动：环境、错误捕获、ProviderScope
│   │   ├── router/              # go_router 声明 + 深链映射
│   │   └── theme/               # ThemeData 装配（消费 design_system/tokens）
│   ├── core/                    # 跨 feature 基建（无业务语义）
│   │   ├── network/             # dio 客户端、拦截器、NDJSON 流解析、错误模型
│   │   ├── storage/             # secure_storage / drift / prefs
│   │   ├── notify/              # 本地通知调度
│   │   ├── health/              # Health Connect / HealthKit 封装
│   │   └── analytics/           # 埋点与崩溃上报（PLT-003）
│   ├── design_system/           # 设计系统：与业务完全解耦，可独立单测
│   │   ├── tokens/              # ThemeExtension：colors / radii / typography / elevation / spacing
│   │   ├── components/          # 卡片、渐变描边卡、chip、开关、任务行、指标卡、进度条、账单行、记忆卡、设置行
│   │   └── orb/                 # AI 核心球：painter + controller + 四态状态机
│   └── features/                # 按业务域，每域三层
│       ├── home/                # data / domain / presentation
│       ├── chat/
│       ├── life/
│       ├── ledger/
│       ├── memory/
│       ├── health/
│       ├── briefing/
│       └── profile/
├── test/
└── integration_test/
```

### 2.1 三条分层纪律（对齐后端的分层铁律）

| # | 纪律 | 理由 |
|---|---|---|
| L1 | `features/*` **不得互相 import**；只允许 import `core/` 与 `design_system/` | 跨域组合一律走 `app/` 层或 `core/` 的共享类型。否则 `home` 会反向依赖 `ledger` 的内部实现 |
| L2 | `design_system/` **不得 import `core/` 或 `features/`** | 设计系统必须能脱离网络与业务独立渲染 → 才能做 golden 测试 |
| L3 | `features/*/presentation` 不得直接调 `dio`；一律经该域 `data/` 的 repository | 保证可 mock、可缓存、可离线降级 |

---

## 3. 数据流：NDJSON 流式对话

这是全 App 最复杂的一条链路，单独说明。

### 3.1 链路

```text
dio.post('/chat/message', responseType: stream, cancelToken)
  → Stream<Uint8List>
  → utf8.decoder.bind(stream)
  → LineSplitter()                        # 按行切分（后端每行一个 JSON）
  → jsonDecode(line)
  → 事件分发：
       turn_meta   → 更新模式 / 意图 / 目标（APP-012）
       token       → 追加正文（APP-010）
       tool_step   → 追加/推进过程卡步骤（APP-013）
       done        → 收口，落历史
       detail/error→ 映射为用户可读文案（APP-008）
  → Riverpod Notifier 更新 ChatTurnState
  → UI 增量重绘
```

### 3.2 四个必须处理的细节

| 细节 | 问题 | 做法 |
|---|---|---|
| **逐 token 重绘** | token 到达频率极高，每个 token 触发一次重绘会掉帧 | **合帧节流**：按 16ms 窗口 flush 累积文本，而非逐 token setState |
| **Markdown 增量渲染** | 流式文本反复解析 Markdown 成本高，且半截语法会闪烁 | 只对**已闭合块**做完整解析，尾部未闭合块按纯文本渲染；或在流式期间降级为轻量格式 |
| **断流** | `done` 未到就结束（网络中断） | 标记 turn 为「不完整」，允许重试；**不得**静默当作正常结束 |
| **取消** | 用户返回或切页 | 持有 `CancelToken`，在页面 dispose 时取消，避免泄漏 |

### 3.3 状态模型（结构性约定）

```text
ChatTurnState {
  status:        idle | streaming | toolRunning | done | failed
  text:          String                 // 正文累积
  memoryRefs:    List<MemoryRef>        // 来自 turn_meta（API-003）
  toolSteps:     List<ToolStep>         // 来自 tool_step（API-002）
  chips:         List<QuickAction>      // 结果卡快捷操作（API-004）
  error:         AppError?
}

ToolStep {
  stepId, toolId, label,
  status: running | done | failed | todo,
  detail: String?,                      // 右侧明细，如「¥35.00」「餐饮 · 午餐」
  target: String?                       // 落点明示，如「已同步到生活 · 记账」
}
```

> ⚠️ **`todo`（未来步）由服务端一次性下发还是客户端推导，必须在 API-002 的 Detail 里冻结**。若服务端只下发已发生的步骤，客户端需要知道总步数才能渲染灰显的「未来步」——这是接口契约问题，不是 UI 问题。

---

## 4. 设计 token 的 Flutter 落地

### 4.1 ⚠️ 先定稿：设计稿自身存在 4 处色值不一致

设计稿的 CSS `:root` 变量、设计稿 §06「视觉规范」色卡、原型 `:root` **三方不一致**：

| token | 设计稿 `:root` | 设计稿 §06 色卡 | 原型 `:root` | **定稿（D9）** |
|---|---|---|---|---|
| 背景（暖纸白） | `#FAF9F6` | `#F5F4F0` | `#F5F4F0` | **`#F5F4F0`**（2:1，且与原型一致） |
| 次文字 | `#62646E` | `#6E7079` | `#6E7079` | **`#6E7079`** |
| 弱文字 | `#9C9DA7` | —（未列） | `#A7A8B1` | **`#A7A8B1`** |
| 分割线 | `#EAE8E1` | —（未列） | `#ECEAE3` | **`#ECEAE3`** |

**已定稿（决策 D9）**：以**设计稿 §06 色卡 + 原型**为准（两者一致，2:1 多数），设计稿 `:root` 的这 4 个值视为笔误。
> 另：设计稿 §04+ 写 Orb 呼吸 **4s**，§06 写 **4.2s** → 以 §06 为准（`AppMotion.orbBreath = 4.2s`）。
> ⚠️ `APP-002` 开工前**必须**已拿到本节的定稿值，否则改色会波及全部 golden 测试。

### 4.2 token 映射表

| 设计稿 token | 值 | Flutter 落点 |
|---|---|---|
| 暖纸白 · 背景 | `#F5F4F0` | `AppColors.canvas` |
| 卡片白 | `#FFFFFF` | `AppColors.surface` |
| 墨 · 主文字 | `#1B1C23` | `AppColors.ink` |
| 次文字 | `#6E7079` | `AppColors.ink2` |
| 弱文字 | `#A7A8B1` | `AppColors.ink3` |
| 分割线 | `#ECEAE3` | `AppColors.line` |
| **AI 渐变 · 品牌** | `#8B6DFF → #4D8DFF(55%) → #2BD2E8` | `AppGradients.ai`（`LinearGradient`，`stops: [0, .55, 1]`，135°） |
| AI 紫 · 强调 | `#7A5CFF` | `AppColors.aiPrimary` |
| AI 蓝 | `#3E8BFF` | `AppColors.aiBlue` |
| AI 青 | `#2BD2E8` | `AppColors.aiCyan` |
| 暖橙 · 关怀/提醒 | `#FF9D76` | `AppColors.warm` |
| 青绿 · 健康/完成 | `#33BC8C` | `AppColors.health` |
| 麦金 · 财务 | `#EFA63C` | `AppColors.money` |
| **深夜紫 · 重点卡** | `#23232E → #37335C(65%) → #4A4390` | `AppGradients.deep` |
| 卡片投影 | `0 10px 30px rgba(27,28,35,.06)` | `AppElevation.card` = `BoxShadow(offset: (0,10), blurRadius: 30, color: ink @ 6%)` |
| 重点卡投影 | `0 16px 36px rgba(30,28,55,.35)` | `AppElevation.deep` |
| 圆角 | 24 / 18 / 12 / 999 | `AppRadii.lg / md / sm / full` |
| 字号 | 标题 24–28 / 700–800；正文 14–15 / 400–550；辅助 11–13 | `AppTypography.display / title / body / caption` |
| 间距 | 页面左右 18；卡间距 11–14；段间隔 24 | `AppSpacing.page(18) / card(12) / section(24)` |
| 动效时长 | Orb 呼吸 4.2s；页面切换 0.38s fadeUp；**全部动效 ≤ 400ms** | `AppMotion.*`（含 `fadeUp` 转场曲线） |

### 4.3 三条 token 纪律

1. **一律经 `ThemeExtension` 取用**，禁止在组件里写 `Color(0xFF...)`。M0 的 C1 验收就是「全仓 grep 无硬编码色值」。
2. **语义色优先于字面色**：`AppColors.aiPrimary` 而非 `purple`；`AppColors.money` 而非 `gold`。设计稿的「语义纪律」——**AI 渐变只用于 AI 的存在与行动**——靠命名约束，不靠自觉。
3. **深色模式靠 token 对调**（暖纸白 ↔ 深夜紫），不在组件里写 if。设计稿 §09 明确要求 token 支持对调，因此 `AppColors` 必须做成 `ThemeExtension` 而非 `static const`。

---

## 5. 四个无法 1:1 平移的视觉点（含具体做法）

### 5.1 AI 结论卡 1.5px 渐变描边

- **问题**：`Container.decoration.border` **不支持渐变**（只有 `BorderSide` 纯色）。
- **做法**：自绘 `CustomPainter`——先按 `RRect`（圆角 24）画 `Gradient` 描边（`Paint..style = stroke..strokeWidth = 1.5..shader = gradient.createShader(rect)`），再让子内容内缩 1.5px 覆盖白底。**不用 `ShaderMask`**（它会把子内容一起着色，需额外反遮罩，成本更高）。
- **落点**：`design_system/components/GradientBorderCard`（APP-007）。

### 5.2 Orb 内层高光的 `mix-blend-mode: screen`

- **问题**：CSS 的 `mix-blend-mode` 在 Flutter 无直接对应。
- **做法**：`Canvas.saveLayer(bounds, Paint())` → 在 layer 内依次绘制底色径向渐变与两层高光径向渐变，第二层起用 `Paint()..blendMode = BlendMode.screen` → `restore()`。
- **注意**：`saveLayer` 开销大，**必须**加 `RepaintBoundary` 包裹，且只在 Orb 可见时开动画。

### 5.3 字体：`-apple-system / PingFang SC`

- **问题**：Android 无 PingFang SC，直接用会导致两端字形差异明显。
- **做法**：定义跨端字体回退链——iOS 用 `PingFang SC`（系统自带，不打包）；Android 用 `HarmonyOS Sans SC` 或思源黑体（**需确认授权后打包**），回退到 `sans-serif`。字体资源不进仓库（体积 + 授权），由构建期拉取。
- **待办**：字体授权确认属 PLT-002 合规范围。

### 5.4 「数字用等宽特性」

- **问题**：默认数字是比例字形，滚动时金额会左右跳动。
- **做法**：所有数值型 `TextStyle` 统一加 `fontFeatures: [FontFeature.tabularFigures()]`——封装成 `AppTypography.numeric` 变体，**禁止在页面上手写数字样式**（否则必然漏）。账本金额、指标卡、进度环全部走它。

---

## 6. Orb（AI 核心球）实现方案

### 6.1 结构

```text
Orb(size, state)
 └── RepaintBoundary
     └── CustomPaint(painter: OrbPainter(progress, state))
         + 一个 AnimationController（呼吸 4.2s，repeat reverse）
         + 一个 AnimationController（swirl 7s，仅 thinking 态启用）
```

### 6.2 四态映射

| 状态 | 视觉 | 实现要点 |
|---|---|---|
| 待机 / 陪伴 | 缓慢呼吸 4.2s，蓝紫渐变 | 单 controller `repeat(reverse: true)`，`scale` 1 → 1.055 |
| 思考 / 执行 | 旋转加速 + 色相流动 | 启用 swirl controller；色相流动用 `BlendMode` 叠加旋转渐变，**不逐帧算 HSV** |
| 主动关怀 | 暖橙轻脉冲 | 换成暖橙渐变色 + 短脉冲曲线（非对称 ease） |
| 完成 / 成长 | 绿色一次绽放 | 一次性动画（`forward()` 后停在终态），需可重置 |

### 6.3 性能与功耗（移动端必须处理）

| 措施 | 原因 |
|---|---|
| `RepaintBoundary` 包裹 | 隔离重绘，避免带动整页 |
| `TickerMode` 感知 | 页面不可见 / App 后台时**必须停表**，否则纯耗电 |
| 首页长列表滚动时降频 | Orb 在首屏顶部，滚动时可暂停或降帧 |
| 禁用逐帧 `Path` 重建 | painter 内缓存不变的 `Path` / `Shader` |

> 落点：`design_system/orb/`（APP-006）。**golden 测试必须覆盖四态 × 两尺寸**，因为它是全站唯一「AI 语义」承载者，视觉回归成本最高。

---

## 7. 缓存与离线策略（V1 范围）

| 数据 | 策略 | 落点 |
|---|---|---|
| 会话历史 | 只读缓存（drift），进页先渲染缓存再刷新 | `features/chat/data` |
| 记忆列表 | 只读缓存 | `features/memory/data` |
| 账本汇总 / 账单 | 只读缓存；**金额展示必须标注数据时间** | `features/ledger/data` |
| 首页聚合 | 只读缓存（用于冷启动骨架 → 数据） | `features/home/data` |
| 写操作（记账 / 勾选任务） | **不在 V1 做离线写**；失败进重试队列，UI 明示「待同步」 | `core/network/retry_queue` |
| 令牌 | `flutter_secure_storage` | `core/storage` |

> **明确不做** Offline-first 的写路径（`requirements-analysis.md` §7 反范围）。读缓存是为了冷启动体验，不是为了离线可用。

---

## 8. 测试策略（PLT-004）

| 层级 | 覆盖对象 | 工具 |
|---|---|---|
| 单元 | token 计算、NDJSON 行解析、状态机转移（tool step 推进）、金额格式化 | `flutter_test`（纯 Dart，无需设备） |
| Golden | **Orb 四态 × 尺寸**、渐变描边卡、指标卡、任务行、账单行、记忆卡 | `matchesGoldenFile` |
| Widget | 页面装配（用 mock repository 注入假数据）、四态（加载/空/错/骨架） | `flutter_test` + `mocktail` |
| 契约 | NDJSON 事件序列回放（用真实后端录制的流做 fixture） | 自定义 fixture runner |
| 集成 | 真机走通：对话流式 → 过程卡 → 记账落库 | `integration_test` |

**关键约定**：NDJSON 事件回放 fixture **必须包含 `tool_step` 序列与断流场景**——这两条是最容易在真实环境出问题、又最难手工复现的路径。

---

## 9. 构建与发布（PLT-005）

| 项 | 做法 |
|---|---|
| flavor | `dev` / `prod` 两套（对应不同后端地址与 bundle id） |
| 配置注入 | 后端地址等经 `--dart-define` 注入，**不写进仓库** |
| 密钥 | 签名密钥与 API Key **绝不进仓库**（AGENTS.md 全局约定） |
| 混淆 | Android 开 R8；iOS 开 bitcode 相关配置 |
| 分发 | Android 内测渠道 + iOS TestFlight |
| CI | 每次提交跑：`analyze` + 单元 + golden；golden 失败**必须人工确认**（视觉变更可能是有意的） |

---

## 10. 已知风险与备选方案

| # | 风险 | 备选 |
|---|---|---|
| 1 | Riverpod 代码生成（`riverpod_generator`）引入构建复杂度 | 退回手写 Provider（`flutter_riverpod` 本身不依赖代码生成），代价是样板增加 |
| 2 | drift 的迁移与后端 Schema 演进不同步 | 客户端缓存表**只存投影**（服务端返回的 DTO），不做本地业务逻辑，降低耦合 |
| 3 | `health` 包对 Health Connect 新权限模型（Android 14+ `VIEW_PERMISSION_USAGE` + `HEALTH_PERMISSIONS`）支持不完整 | 该部分直接走平台通道，包仅用于数据读取 |
| 4 | 字体授权未落实 | 先用系统默认字体跑通全流程，字体切换只影响 token 层，不阻塞开发 |
| 5 | golden 测试在 CI 与本地渲染不一致（字体抗锯齿差异） | 用固定容器镜像跑 golden，或在 CI 中标记为「非阻塞告警」 |
| 6 | **M3 默认样式「漏」出来**（色渗、pill indicator、默认字号阶） | `app/theme/` 逐项覆盖 + PLT-004 加 M3 特征回归 golden；一旦发现漏出，**先改主题层，禁止在业务组件里打补丁** |
| 7 | **三生成器 `.g.dart` 互相覆盖** | APP-001 完成 `build.yaml` 输出后缀隔离（drift 用 `.drift.dart`）+ 约定「一个文件只被一个生成器处理」+ CI 校验生成物 |

---

## 11. 开工顺序建议（与 `tasks.md` 的 M0 对齐）

```text
① 定稿设计 token（§4.1 的 4 处色值）      ← 必须先做，否则全量返工
② APP-001 工程骨架（含 build.yaml 三生成器隔离）
③ APP-002 token 层 + M3 覆盖层  →  ④ APP-006 Orb   ← 设计系统核心，可并行做 golden 基建
⑤ APP-003 网络层（含 ChatEvent union）→  ⑥ APP-004 存储
⑦ APP-005 导航骨架  →  ⑧ APP-007 组件库  →  ⑨ APP-008 状态规范
                                          ↓
                                    M0 收口点 C1
```

**M0 阶段的三个「一票否决」自检**（任一不通过就不算完成）：

1. 全仓 grep **无硬编码色值**，token 一律经 `ThemeExtension`；
2. 截图与设计稿比对，**无 M3 默认视觉特征**（色渗 / pill indicator / 字号阶偏移）；
3. `build_runner build` 后 `git diff --exit-code` **干净**（生成物已提交、无互相覆盖）。

**可立即并行开工的后端任务**：`API-001`（鉴权）、`API-002`（工具事件）——两者均不依赖客户端，且 `API-002` 是 M1 收口点 C2 的关键路径。
