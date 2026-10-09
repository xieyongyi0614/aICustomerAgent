# 朝夕 App（`apps/mobile`）— Flutter 客户端

「朝夕」AI Personal Life Agent 的移动客户端（V5.0.0 新开产品轴）。定位是**产品级 App**，与 `apps/frontend/`（React 调试控制台）**零复用**；服务端为 `apps/backend/`（FastAPI），客户端只消费产品级 API（`API-*` 任务线新增），不感知内部编排。

技术栈：Flutter + Riverpod 3 + GoRouter + Dio + Freezed + Drift(SQLite) + Flutter Hooks，Material 3 仅作交互底座、视觉由自研设计系统接管。

## 环境要求

- **Flutter ≥ 3.44.0（含 Dart ≥ 3.13.4）** —— 由 `pubspec.yaml` 与 `pubspec.lock` 的 SDK 约束决定。先 `flutter --version` 核对；版本过低会在 `pub get` 时直接报 `version solving failed`。
- 目标平台：**Android / iOS**。仓库带 web / windows / macos / linux 脚手架目录，但产品验收以移动端为准。
- 后端就绪：见根 README「快速开始」起后端，并在 `apps/backend/.env` 配置（清单见 `apps/backend/.env.example`）：
  - `REDIS_URL` + `EMAIL_SMTP_*` —— 邮箱验证码登录依赖（缺一登录端点 503）
  - `AUTH_TOKEN_SECRET` —— 设备令牌 HMAC 签名密钥

## 快速启动

### 1. 拉依赖

```bash
cd apps/mobile
flutter pub get
```

### 2. 代码生成（按需）

改动下列形态的源文件后才需要重跑；三生成器**输出隔离**（一个源文件只被一个生成器处理，禁止混写，约定见 `build.yaml` 头注）：

```bash
dart run build_runner build --delete-conflicting-outputs
```

| 源文件形态 | 生成器 | 产物 |
|---|---|---|
| `*_model.dart` / `*_event.dart` | freezed + json_serializable | `*.freezed.dart` + `*.g.dart` |
| `*_db.dart` / `*_table.dart` | drift_dev（PartBuilder） | `*.drift.dart` |
| `*_provider.dart` | riverpod_generator | `*.g.dart` |

### 3. 准备 Android 设备（模拟器 / 真机）

两种设备共用同一条地址约定：**设备侧统一用 `127.0.0.1:8020` 访问宿主机后端**（模拟器与真机 USB 都靠 `adb reverse` 打通），只有真机走局域网直连时才改用电脑 IP。

#### 3.1 模拟器（Android 开发必读）

**模拟器必须手动拉起——它不会随 `flutter run` / F5 自动启动。** 没起模拟器时不会报「找不到设备」，而是**静默挑一个其它设备**（本机是 `windows` 桌面）；本机未装 Visual Studio，`-d windows` 构建必然失败，最终现象是**模拟器和应用都没弹出来**，极易误判成「模拟器坏了」。

每次开发前先拉起（首次开机较慢）：

```bash
emulator -avd Medium_Phone_API_36                 # 直接用 emulator.exe 启动，最稳
flutter emulators --launch Medium_Phone_API_36    # 等价写法；列表用 flutter emulators 查看
```

> `emulator` / `adb` 来自 `%ANDROID_HOME%\emulator` 与 `%ANDROID_HOME%\platform-tools`（已在系统 PATH）。若 `flutter emulators` 报 `CreateFile failed 231`（Dart 工具链建管道失败），改用上面的 `emulator -avd` 直启，绕开 flutter 工具链。

等开机完成：`adb devices` 出现 `emulator-5554`，且 `adb -s emulator-5554 shell getprop sys.boot_completed` 返回 `1`。**开机完成后还要选对设备**：

- **VS Code（F5）**：先在底部状态栏把设备切到 `emulator-5554` 再 F5。仓库根两个「朝夕 App」启动配置**不带 `deviceId`**，只会跑在「当前选中设备」上；没切就会跑到 `windows` 上，表现同上。
- **CLI**：显式带 `-d emulator-5554`（见 §4）。

然后**重建端口隧道**：

```bash
adb reverse tcp:8020 tcp:8020
```

模拟器是带独立网络栈的虚拟机，它的 `127.0.0.1` 是它自己——reverse 之后模拟器里的 `127.0.0.1:8020` 才指向宿主机后端（`dart_defines/dev.json` 即按此地址约定）。**reverse 在模拟器重启后丢失**，App 报「网络好像断了」时先重跑这条。

关闭模拟器用 `adb emu kill` 或直接关窗口。已知坑：`adb emu kill` 可能残留 AVD 锁（`~/.android/avd/Medium_Phone_API_36.avd/` 下的 `*.lock`，锁可能是**目录**，用 `rm -rf` 删）——残留后下次启动崩溃、`flutter run` 回落到 `windows` 等其它设备，删锁再拉起即可。

#### 3.1.1 模拟器定位（天气城市依赖）

**模拟器出厂没有任何位置**（系统 `last location` 全为 null，51 分钟 locations=0），天气会一直落到「默认北京」。同时低精度定位走的是**网络定位 provider（GMS）**，模拟器没有 WiFi / 基站数据源，永远拿不到 fix——App 内已做降级：低精度限时 2 秒，超时自动换高精度走 GPS，GPS 由下面的注入供位。真机不受影响（网络定位正常）。

给模拟器注入位置（二选一）：

- **Extended Controls（推荐，持续生效）**：模拟器工具栏 `⋯` → Location → 搜索/点选目标城市（如广州）→ `SET LOCATION`。设置后 GPS 引擎每次出 fix 都用这个位置。
- **`adb emu geo fix`（一次性）**：`adb emu geo fix <经度> <纬度> [海拔] [卫星数]`（注意**经度在前**，如广州 `adb emu geo fix 113.2644 23.1291 50 12`）。坑：GPS 引擎没被任何请求启动时（`dumpsys location` 里 `mStarted=false`）注入会被丢弃——先打开 App 触发定位（首页加载后 5 秒窗口内）再注入，或在注入后重启 App 再看结果。

验证：`adb shell dumpsys location | grep "last location"` 出现坐标即注入成功；App 侧看 logcat `[geo]` 日志（与 `[net]` 同惯例，仅 debug 构建输出），如 `[geo] LocationAccuracy.high 定位成功: 23.1291,113.2643983`。

#### 3.2 真机（USB 调试）

**前置**：手机连点「版本号」开启开发者选项 → 打开「USB 调试」（vivo / 小米 / OPPO 等还需打开「USB 安装」或「USB 调试（安全设置）」）；插线后手机上弹「允许 USB 调试」点允许。

```bash
adb devices -l        # 出现 <设备号> device product:... 即授权成功（unauthorized = 手机上还没点允许）
flutter devices       # 取 device-id（即 adb 的设备号）
```

**方式 A：USB + `adb reverse`（推荐；地址与模拟器完全一致，不依赖局域网与防火墙）**

```bash
adb -s <device-id> reverse tcp:8020 tcp:8020
flutter run --dart-define-from-file=dart_defines/dev.json --flavor dev -d <device-id>
```

隧道把设备侧的 `127.0.0.1:8020` 指到电脑上的后端，因此这条路要求 `API_BASE_URL` 是 `http://127.0.0.1:8020/api/v1`：`dart_defines/dev.json` 为该值时直接跑；若它已被改成局域网 IP（见方式 B），加 `--dart-define=API_BASE_URL=http://127.0.0.1:8020/api/v1` 覆盖。插拔 USB / 手机重启后隧道失效，重跑 `adb reverse`（多设备同时在线时务必带 `-s <device-id>`）。

**方式 B：同局域网直连（不插线）**

1. 手机与电脑连同一 Wi-Fi；
2. 后端监听全网卡：`uvicorn app.main:app --host 0.0.0.0 --port 8020`（仓库根 `.vscode/launch.json` 的「FastAPI 后端」已是 `0.0.0.0`）；
3. 真机连不上时先查 Windows 防火墙是否拦了 Python 入站（启动时的弹窗选「允许专用网络」，或到「Windows Defender 防火墙 → 允许应用通过防火墙」补勾）；
4. `ipconfig` 查电脑 IPv4（与手机同网段那个），写进 `dart_defines/dev.json`（入库默认值是 `127.0.0.1:8020/api/v1`，走局域网时改成电脑 IP，换网络后要同步改），或运行时覆盖：

```bash
flutter run --dart-define-from-file=dart_defines/dev.json \
  --dart-define=API_BASE_URL=http://192.168.2.101:8020/api/v1 \
  --flavor dev -d <device-id>
```

**真机须知**

- `API_BASE_URL` **必须带 `/api/v1` 前缀**：Dio 以它作 baseUrl、请求路径直接拼在其后（`/auth/email/code` → `…:8020/api/v1/auth/email/code`），漏前缀会全量 404。
- dev 包 applicationId 为 `com.example.mobile.dev`、应用名「朝夕 Dev」（`android/app/build.gradle.kts` 的 productFlavors），与模拟器同名包、正式包互不覆盖，可同机共存。
- 明文 HTTP 可用（`targetSdk 36` 未配 `usesCleartextTraffic`，Flutter 请求走 Dart 侧网络栈），真机无需额外加网络安全配置。
- **装机方式**：真机用 `flutter run -d <device-id>` / `flutter install -d <device-id>`（工具按设备 ABI 构建并安装）。**别把 `flutter build apk` 的产物直接扔给真机**——若该 APK 只含模拟器 ABI（x86_64）的引擎，真机一启动就白屏闪退，日志特征：
  `MissingLibraryException: Could not find 'libflutter.so'. Looked for: [arm64-v8a, armeabi-v7a, armeabi], but only found: [x86_64]`。
  必须出包时显式指定：`flutter build apk --debug --flavor dev --target-platform android-arm64`，再核对产物确实含 `lib/arm64-v8a/libflutter.so`（`unzip -l`，或 `aapt2 dump badging` 看 `native-code`）。
- 排查：`adb logcat -s flutter` 看 `[net] req` / `[net] err`，闪退看 `adb logcat | grep AndroidRuntime`；`unauthorized` → 重新插线在手机上点允许；`no devices` → 换数据线、装厂商 USB 驱动。

### 4. 运行

API 地址经 `--dart-define` 注入，**未注入时启动即崩**（`lib/core/env/app_env.dart` fail-fast，无静默回退硬编码地址）。三种方式任选：

**VS Code（最简）**：仓库根 `.vscode/launch.json` 已带「朝夕 App · Android/iOS 模拟器 (dev)」两个启动配置，F5 一键运行。这两个配置**不带 `deviceId`**，只会跑在「当前选中设备」上——所以 **F5 前必须先手动拉起模拟器，并把状态栏设备切到 `emulator-5554`**（见 §3.1）。真机 + 模拟器同时在线时同理，先在下拉设备选择器里选中目标设备再 F5。选错设备不报错，只会静默跑到别的设备上（本机无 Visual Studio，跑到 `windows` 会直接构建失败、什么都不弹）。

**CLI（推荐）**：地址收敛在 `dart_defines/dev.json`，改地址只动这一处：

```bash
flutter run --dart-define-from-file=dart_defines/dev.json \
  --flavor dev -d emulator-5554                    # Android 模拟器（--flavor dev 必带，Gradle productFlavors）

flutter run --dart-define-from-file=dart_defines/dev.json \
  --flavor dev -d <device-id>                      # Android 真机（USB：先按 §3.2 建 adb reverse）

flutter run --dart-define-from-file=dart_defines/dev.json \
  --dart-define=API_BASE_URL=http://localhost:8020/api/v1 \
  --flavor dev                                     # iOS 模拟器（共享宿主网络，后项覆盖文件值）
```

**原始方式（兜底）**：

```bash
flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8020/api/v1 --flavor dev
```

`APP_FLAVOR` 默认 `dev`；正式部署时在 `dart_defines/` 下新增 `prod.json` 即可（该目录入库，勿放密钥）。

### 5. 首次登录（邮箱验证码）

鉴权走邮箱验证码登录：登录页输入邮箱 → 后端经 SMTP 发 6 位验证码（Redis 存码 + 单次消费）→ 输码调 `POST /auth/email/verify` 换取 30 天期令牌写入 Keychain / Keystore（`flutter_secure_storage`），未注册邮箱自动建号；后续请求由 `AuthInterceptor` 注入 `Authorization: Bearer`，令牌过期 401 重新登录。原「设备配对」链路已退役。

## 目录结构

```text
lib/
├── app/               # 应用壳：bootstrap（时区/本地通知/令牌预载）、GoRouter 路由与 Tab 壳层、Material 3 覆盖层主题
├── core/              # 横切基建
│   ├── env/           #   --dart-define 注入（fail-fast）
│   ├── network/       #   Dio 工厂、auth/错误映射/日志脱敏拦截器、NDJSON 流解析、Freezed 事件 union、重试队列
│   ├── storage/       #   Drift 缓存库（服务端 DTO 投影）、SecureTokenStore、PrefsStore
│   ├── updater/       #   应用内更新：版本检查、策略裁决、流式下载（Range 续传）、双校验、原生安装通道
│   └── notify/        #   早/晚简报本地通知（时间随用户偏好）
├── design_system/     # tokens（色/字/距/径/影/动效/Lucide 图标）、components、orb（AI 核心球）
└── features/          # 按域垂直切分：data / domain / presentation
    ├── home/          #   首页聚合
    ├── life/          #   生活记录与随手记
    ├── ledger/        #   账本
    ├── chat/          #   流式对话（NDJSON 增量渲染 + 本地历史缓存投影）
    ├── memory/        #   长期记忆
    ├── health/        #   健康（含授权同意流）
    ├── briefing/      #   早/晚简报
    └── profile/       #   我的（登录 / 隐私与数据导出删除）
```

## 路由与页面

GoRouter 全量路由（壳层 Tab 5 位：首页 / 动态 / 对话 / 生活 / 我的，各页 chrome 由 `lib/app/router/app_router.dart` 的 `RouteChrome` 统一声明）：

| 路由 | 页面 |
|---|---|
| `/home` · `/dynamic` · `/chat` · `/life` · `/profile` | 主 Tab 五页（`/dynamic` 是可变「动态」位，默认渲染记账；在生活页拖动模块卡重排，宫格第一格即改设） |
| `/chat/ledger?conversationId=` | 对话记账台账 |
| `/ledger` | 账本页 |
| `/briefing?form=morning\|evening` | 早/晚简报（通知点开直达） |
| `/health` · `/health/consent` | 健康页 / 健康授权同意 |
| `/profile/privacy` | 隐私（数据导出与删除） |
| `/profile/about` | 关于（版本真值 / 检查更新 / 仅 Wi-Fi 下载；skill 登记 `B20 #about`） |

## 依赖的后端 API（前缀 `/api/v1`）

| 端点 | 用途 |
|---|---|
| `POST /auth/email/code` · `POST /auth/email/verify` | 邮箱验证码登录（发码 / 验码换长期令牌） |
| `GET /home/summary` | 首页聚合（今日事项 / 花销 / 健康） |
| `POST /chat/message` | 流式对话（NDJSON 事件流，Freezed union 建模 + 增量 Markdown 渲染） |
| `GET /ledger/summary` · `GET/POST /ledger/entries` | 账本汇总与条目（记账四步） |
| `GET /memory/items` · `POST /memory/items/{id}/forget` | 长期记忆查询与遗忘 |
| `GET /life/data` · `GET /life/export` · `DELETE /life/data` | 生活数据读取 / 导出 / 删除（隐私页） |
| `GET /brief/{form}` · `GET/PUT /brief/prefs/me` | 早/晚简报内容与偏好 |
| `GET /health/score` · `POST /health/sync` | 健康分与数据同步 |
| `GET /app-release/latest` | 检查更新（`platform` / `channel` / `version_code`；无更新返回 `200 + has_update:false`） |
| `GET /app-release/artifacts/{id}/download` | 制品下载（支持 `Range` 断点续传；不鉴权——冷启动路径不可依赖 token） |

## 测试

```bash
flutter test                    # 单元 + widget + golden（18 个测试文件）
flutter test integration_test   # 冒烟（app_smoke_test）
```

- **golden 视觉回归**：`test/design_system/goldens/`（组件）与 `test/design_system/orb/goldens/`（Orb 状态 × 尺寸）。改动组件视觉后更新基线：`flutter test --update-goldens test/design_system`。
- **分层守护**：`test/scaffold/layer_guards_test.dart` 以源码静态断言守护目录分层与骨架完整性，新目录 / 新域需同步登记。

## 设计系统与开发约定

- **UI 唯一真源**：`.agents/skills/zhaoxi-design-system/`（优先级高于 `design/` 下设计稿）。任何 UI / 样式工作前先读其 `SKILL.md`。
- **图标系统**：Lucide 本地 TTF + 生成器 + cmap 守卫测试，码点不手抄、不加图标包——详见 [`docs/icons.md`](docs/icons.md)。
- **Material 3 五禁令**：不用 `ColorScheme.fromSeed`（手工构造 `ColorScheme`）、不用 M3 默认 `TextTheme`、显式关闭 `surfaceTintColor`、图标用 Lucide 不用 Material Icons、Tab 栏自绘（中位悬浮 Orb）。视觉不得出现 M3 默认特征（色渗 / pill indicator / 默认字号阶）。
- **状态与 Hooks 边界**：业务状态一律 Riverpod provider（`*_provider.dart` 走生成器）；Flutter Hooks 仅限 widget 级临时资源（Orb 动画控制器 / 输入控制器 / 节流），不承载业务逻辑、不与 `StatefulWidget` 混用。
- **客户端缓存**：Drift 只存服务端 DTO 投影，不做本地业务逻辑；令牌只进 `flutter_secure_storage`，`shared_preferences` 只存非敏感偏好。

## 文档导航

- `docs/version/v5.0.0/requirements-analysis.md` — 需求条目化与 11 条决策
- `docs/version/v5.0.0/flutter-architecture.md` — Flutter 端技术方案（选型评估 / 分层 / Orb 落地路径）
- `docs/version/v5.0.0/tasks.md` + `tasks/` — 任务注册表（41 任务 / APP- · API- · PLT- 三条任务线）与 Task Detail
- `docs/version/v5.0.0/traceability.md` — 设计稿 119 条要求 → 任务的全量覆盖矩阵
