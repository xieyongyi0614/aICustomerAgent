# 朝夕 App（`apps/mobile`）— Flutter 客户端

「朝夕」AI Personal Life Agent 的移动客户端（V5.0.0 新开产品轴）。定位是**产品级 App**，与 `apps/frontend/`（React 调试控制台）**零复用**；服务端为 `apps/backend/`（FastAPI），客户端只消费产品级 API（`API-*` 任务线新增），不感知内部编排。

技术栈：Flutter + Riverpod 3 + GoRouter + Dio + Freezed + Drift(SQLite) + Flutter Hooks，Material 3 仅作交互底座、视觉由自研设计系统接管。

## 环境要求

- **Flutter ≥ 3.44.0（含 Dart ≥ 3.13.4）** —— 由 `pubspec.yaml` 与 `pubspec.lock` 的 SDK 约束决定。先 `flutter --version` 核对；版本过低会在 `pub get` 时直接报 `version solving failed`。
- 目标平台：**Android / iOS**。仓库带 web / windows / macos / linux 脚手架目录，但产品验收以移动端为准。
- 后端就绪：见根 README「快速开始」起后端，并在 `apps/backend/.env` 配置：
  - `AUTH_PAIRING_CODE` —— 设备配对码（客户端配对页输入的就是它）
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

### 3. 运行

API 地址经 `--dart-define` 注入，**未注入时启动即崩**（`lib/core/env/app_env.dart` fail-fast，无静默回退硬编码地址）。三种方式任选：

**VS Code（最简）**：仓库根 `.vscode/launch.json` 已带「朝夕 App · Android/iOS 模拟器 (dev)」两个启动配置，F5 一键运行。

**CLI（推荐）**：地址收敛在 `dart_defines/dev.json`，改地址只动这一处：

```bash
flutter run --dart-define-from-file=dart_defines/dev.json                  # Android 模拟器（10.0.2.2 = 宿主机回环）

flutter run --dart-define-from-file=dart_defines/dev.json \
  --dart-define=API_BASE_URL=http://localhost:8020                         # iOS 模拟器（后项覆盖文件值）

flutter run --dart-define-from-file=dart_defines/dev.json \
  --dart-define=API_BASE_URL=http://192.168.x.x:8020                       # 真机（同一局域网，替换为电脑 IP）
```

**原始方式（兜底）**：

```bash
flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8020 --dart-define=APP_FLAVOR=dev
```

`APP_FLAVOR` 默认 `dev`；正式部署时在 `dart_defines/` 下新增 `prod.json` 即可（该目录入库，勿放密钥）。

### 4. 设备配对（首次使用）

鉴权走「配对码换长期令牌」（API-001）：进入 `我的 → 设备配对`，输入部署侧 `AUTH_PAIRING_CODE` 对应的配对码，客户端 `POST /auth/pair` 换取 30 天期令牌并写入 Keychain / Keystore（`flutter_secure_storage`）；后续请求由 `AuthInterceptor` 注入 `Authorization: Bearer`。令牌过期后 401，重新配对即可。

## 目录结构

```text
lib/
├── app/               # 应用壳：bootstrap（时区/本地通知/令牌预载）、GoRouter 路由与 Tab 壳层、Material 3 覆盖层主题
├── core/              # 横切基建
│   ├── env/           #   --dart-define 注入（fail-fast）
│   ├── network/       #   Dio 工厂、auth/错误映射/日志脱敏拦截器、NDJSON 流解析、Freezed 事件 union、重试队列
│   ├── storage/       #   Drift 缓存库（服务端 DTO 投影）、SecureTokenStore、PrefsStore
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
    └── profile/       #   我的（设备配对 / 隐私与数据导出删除）
```

## 路由与页面

GoRouter 全量路由（壳层 Tab 5 位、各页 chrome 由 `lib/app/router/app_router.dart` 的 `RouteChrome` 统一声明）：

| 路由 | 页面 |
|---|---|
| `/home` · `/life` · `/chat` · `/memory` · `/profile` | 主 Tab 五页 |
| `/chat/ledger?conversationId=` | 对话记账台账 |
| `/ledger` | 账本页 |
| `/briefing?form=morning\|evening` | 早/晚简报（通知点开直达） |
| `/health` · `/health/consent` | 健康页 / 健康授权同意 |
| `/profile/pairing` · `/profile/privacy` | 设备配对 / 隐私（数据导出与删除） |

## 依赖的后端 API（前缀 `/api/v1`）

| 端点 | 用途 |
|---|---|
| `POST /auth/pair` | 设备配对换长期令牌 |
| `GET /home/summary` | 首页聚合（今日事项 / 花销 / 健康） |
| `POST /chat/message` | 流式对话（NDJSON 事件流，Freezed union 建模 + 增量 Markdown 渲染） |
| `GET /ledger/summary` · `GET/POST /ledger/entries` | 账本汇总与条目（记账四步） |
| `GET /memory/items` · `POST /memory/items/{id}/forget` | 长期记忆查询与遗忘 |
| `GET /life/data` · `GET /life/export` · `DELETE /life/data` | 生活数据读取 / 导出 / 删除（隐私页） |
| `GET /brief/{form}` · `GET/PUT /brief/prefs/me` | 早/晚简报内容与偏好 |
| `GET /health/score` · `POST /health/sync` | 健康分与数据同步 |

## 测试

```bash
flutter test                    # 单元 + widget + golden（18 个测试文件）
flutter test integration_test   # 冒烟（app_smoke_test）
```

- **golden 视觉回归**：`test/design_system/goldens/`（组件）与 `test/design_system/orb/goldens/`（Orb 状态 × 尺寸）。改动组件视觉后更新基线：`flutter test --update-goldens test/design_system`。
- **分层守护**：`test/scaffold/layer_guards_test.dart` 以源码静态断言守护目录分层与骨架完整性，新目录 / 新域需同步登记。

## 设计系统与开发约定

- **UI 唯一真源**：`.agents/skills/zhaoxi-design-system/`（优先级高于 `design/` 下设计稿）。任何 UI / 样式工作前先读其 `SKILL.md`。
- **Material 3 五禁令**：不用 `ColorScheme.fromSeed`（手工构造 `ColorScheme`）、不用 M3 默认 `TextTheme`、显式关闭 `surfaceTintColor`、图标用 Lucide 不用 Material Icons、Tab 栏自绘（中位悬浮 Orb）。视觉不得出现 M3 默认特征（色渗 / pill indicator / 默认字号阶）。
- **状态与 Hooks 边界**：业务状态一律 Riverpod provider（`*_provider.dart` 走生成器）；Flutter Hooks 仅限 widget 级临时资源（Orb 动画控制器 / 输入控制器 / 节流），不承载业务逻辑、不与 `StatefulWidget` 混用。
- **客户端缓存**：Drift 只存服务端 DTO 投影，不做本地业务逻辑；令牌只进 `flutter_secure_storage`，`shared_preferences` 只存非敏感偏好。

## 文档导航

- `docs/version/v5.0.0/requirements-analysis.md` — 需求条目化与 11 条决策
- `docs/version/v5.0.0/flutter-architecture.md` — Flutter 端技术方案（选型评估 / 分层 / Orb 落地路径）
- `docs/version/v5.0.0/tasks.md` + `tasks/` — 任务注册表（41 任务 / APP- · API- · PLT- 三条任务线）与 Task Detail
- `docs/version/v5.0.0/traceability.md` — 设计稿 119 条要求 → 任务的全量覆盖矩阵
