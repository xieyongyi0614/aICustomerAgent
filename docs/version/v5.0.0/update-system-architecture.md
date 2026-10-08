# V5.0.0 朝夕 App —— 全量自动更新系统技术方案（更新域）

> **上游**：`docs/version/v5.0.0/tasks.md` §15.11 待回写台账 #7（`tasks.md:639`，明确「缺口尚未立任务，待并入 `PLT-002` / `PLT-005` 或另开注册」）· `docs/version/v5.0.0/compliance/self-distribution-guide.md` §5 / §7（`self-distribution-guide.md:107-114`、`:134-144`）· `docs/version/v5.0.0/compliance/android-store-release-guide.md` §9（`android-store-release-guide.md:297-302`）。
> **范围**：**仅 Android 自有渠道侧载自更新**（`apps/mobile/` + `apps/backend/` + 发布基建）。iOS 自更新、Google Play In-App Updates、国内应用商店跳转**均不在本期**。
> **本期能力面**：**全量 APK 下载安装**。增量（差分）**只预留契约，不实现**（见 §10）。
> **交付形态**：本文档 + 三份 Task Detail（`APP-044` / `API-022` / `PLT-008`）。**本次代码零改动**。
> **用户裁决来源**：2026-10-08 四问四答（平台与渠道 = Android 侧载自更新；增量方案 = 先全量、只预留 patch 字段；制品托管 = 后端自建；交付形态 = 仅设计文档）。
> **体例**：沿用 `docs/version/v5.0.0/flutter-architecture.md` 与 `docs/version/v5.0.0/tasks/README.md`；UI 部分以 `.agents/skills/zhaoxi-design-system/` 为唯一真源。

---

## 1. 选型与裁决

### 1.1 逐项选型评估

| 关注点 | 选型 | 评估 | 约束 / 说明 |
|---|---|---|---|
| 更新通道 | **自有后端分发 + 应用内安装** | ✅ 唯一可行路径 | 未上架商店（`self-distribution-guide.md:17`「不上架 = 失去商店自动更新」），版本告知、下载、安装引导必须自己承担 |
| 本地版本读取 | **`package_info_plus`**（唯一新增依赖） | ✅ 必需 | 现状无任何版本读取能力（`android-store-release-guide.md:244`「未引入 `package_info_plus`」）；`profile_page.dart:509` 的版本行是硬编码串 |
| 安装通道 | **Kotlin 原生 + `MethodChannel`** | ✅ 必需 | Flutter 无标准安装 API；`MainActivity.kt` 已继承 `FlutterFragmentActivity`，可承载 Channel 与权限跳转 |
| 文件暴露 | **FileProvider（`content://`）** | ⚠️ **硬阻断项** | Android 7.0+ 用 `file://` 直接 `FileUriExposedException`；现状 `AndroidManifest.xml:19-55` **无任何 `<provider>`** |
| 安装授权 | **`REQUEST_INSTALL_PACKAGES` + `canRequestPackageInstalls()` 引导** | ⚠️ **硬阻断项** | Android 8.0+ 缺该权限无法调起安装器；现状 `AndroidManifest.xml:4-18` **未声明** |
| 制品托管 | **后端本地目录 / Docker volume** | ✅ 零外部依赖 | 后端无对象存储能力（唯一 `StaticFiles` 在 `scripts/serve_with_frontend.py:12,24`，只托管前端 `dist`）；内测阶段足够 |
| 下载传输 | **Dio 流式写盘 + HTTP Range 断点续传** | ✅ 复用既有基建 | `core/network/dio_client.dart:31-42`（共享实例 + 拦截器链）可直接复用 |
| 校验 | **sha256 + APK 签名指纹双校验** | ✅ 不可省略 | 见 §5.4；签名指纹需覆盖 `build.gradle.kts:62-66` 的 release 缺失回退 debug 场景 |
| 状态管理 | **Riverpod `Notifier`** | ✅ 无异议 | 对齐 `apps/mobile/README.md:214-218`「业务状态一律 Riverpod provider」 |
| 后端接口 | **FastAPI 独立模块 + 单表** | ✅ 无异议 | 形态对齐 `app/api/v1/car.py`（单文件、内联 schema、零仓储依赖先例） |
| 数据面 | **Alembic `0009` 增量迁移建一张表** | ✅ 无异议 | 链尾 `0008`（`tests/support/schema_pins.py:13`） |

### 1.2 明确不引入（被否决方案 + 理由）

| 方案 | 否决理由 |
|---|---|
| **APK 二进制差分（bsdiff / HDiffPatch / bspatch）** | 用户裁决本期不做。差分需端侧原生合成 + 服务端出包流水线双改造，且每次发布要维护「基线版本 × 目标版本」的补丁矩阵；先在全量链路上把**校验与安装**这两处最难回头的环节做对，再叠差分。契约已预留（§10） |
| **Split APK / App Bundle 按 ABI + 密度拆包下发** | 侧载渠道下 AAB 不能直接安装；按 ABI 拆包收益远小于差分，且要改造构建与制品命名体系。当前 `README.md:114-119` 已在装机说明里要求显式指定 `--target-platform android-arm64`，收益已部分取得 |
| **Flutter Dart 层 OTA 代码热更（Shorebird 类）** | 只替换 Dart 代码、原生改动仍需发版，会形成「两条发布通道」的心智负担；且自有渠道下合规披露成本 > 收益。本期不做 |
| **`in_app_update`** | Google Play 专属 API，与「自有渠道侧载」不匹配（`self-distribution-guide.md:98` 的场景就是「应用市场搜不到」） |
| **`upgrader` / `flutter_ota` 类模板包** | 模板化 UI（自带对话框与文案），与设计系统「UI 唯一真源」正面冲突；且无法接入端侧自定义策略（force / recommend / ignore）与原生安装链路 |
| **对象存储 + CDN（OSS / R2）** | 用户裁决「后端自建」。内测阶段并发与带宽压力可忽略；`download_url` 字段保持**绝对/相对 URL 皆可**的形态，将来换 CDN 只改配置不改契约 |
| **第三方分发平台（蒲公英 / fir.im / Bugly）** | 会把版本元数据的所有权让渡给第三方（且与后端已有用户体系无法打通）；本期不引入 |
| **iOS 自更新** | 平台不允许。本期设计仅在 `platform` 字段保留 `ios` 语义位，不实现 |
| **后台静默安装** | Android 平台不允许（安装必须由前台 Activity 发起并经用户确认）；写入反范围 |
| **灰度按百分比投放** | 无实现即死字段，违反「不留无实现的契约」。将来要上只需改服务端选取逻辑，**不必改契约** |
| **新增 `*_enabled` 功能开关** | 全局约束（`tasks/README.md:93`） |

### 1.3 三份任务明细（本次一并产出）

| Task ID | 名称 | 交付面 | 依赖 | 说明 |
|---|---|---|---|---|
| `PLT-008` | 制品打包与版本发布 | 打包脚本 + 制品命名/归档 + `release-manifest` + 版本元数据写入 | `PLT-005`（构建出签名 APK）、`APP-001`（flavor） | 发布线。**边界见 §7.3** |
| `API-022` | 后端版本与制品服务 | 迁移 `0009` + release 表 + 两个端点 + 参数类设置 | `PLT-008`（制品与元数据规范） | 服务线。挂载点 `app/api/v1/router.py:20-36` |
| `APP-044` | 客户端全量更新能力 | `core/updater/` + 原生安装通道 + 更新弹层 + 关于页 + 版本行真值化 | `API-022`、`APP-001`、`APP-002`（token） | 客户端线 |

> **编号依据**：`tasks.md` §15.10 任务编号占用登记表（`tasks.md:620-627`）在立项前明示下一可用号为 `APP-044` / `API-022` / `PLT-008`，本批已按此占用，并把该表的「下一可用号」bump 为 `APP-045` / `API-023` / `PLT-009`；本批注册见 `tasks.md` §18。**注意** `API-021` 已于 2026-10-07 被「首页每日 AI 总结生成器」占用（`tasks.md:672-678`），**不得复用**。

---

## 2. 现状证据（缺口清单）

### 2.1 客户端：更新能力零基础

| 事实 | 证据 |
|---|---|
| 唯一版本真相 = `pubspec.yaml` 的 `0.1.0+1` | `apps/mobile/pubspec.yaml:4` |
| 无任何更新类依赖（`package_info_plus` / `in_app_update` / `upgrader` / `shorebird`） | `apps/mobile/pubspec.yaml:9-37`；`pubspec.lock` 同类关键词 0 匹配 |
| `lib/` 内零更新相关代码 | 全量搜索 `update` / `upgrade` / `check_version` / `PackageInfo` / `apk` / `install` **零真实命中**（命中项均为 `total` / `expenseTotal`） |
| 启动链路无更新检查挂点 | `apps/mobile/lib/app/bootstrap.dart:19-50`（`WidgetsFlutterBinding.ensureInitialized()` → `AppEnv.ensureInitialized()` → 时区 → `SecureTokenStore` → `LocalBriefNotifier` → `ProviderContainer` → `runApp`） |
| 无「关于」页、无 `/profile/about` 路由 | `apps/mobile/lib/app/router/app_router.dart:159-243`（routes 列表）；`lib/` 内 `/profile/about` 与 `AboutPage` **0 命中** |
| 设置页「设置组」是现成挂载处（`A26`） | `profile_page.dart:383-437`（`SettingGroup`）与 `:385-435`（`SettingRow`：记忆管理 / 飞书账号 / 隐私设置） |
| 版本行为**硬编码串**，与 `pubspec.yaml` 无绑定 | `profile_page.dart:509`「朝夕 v0.1.0 (MVP) · Personal AI OS 的第一步」；已由合规文档登记（`android-store-release-guide.md:244`、`self-distribution-guide.md:139`） |
| 原生侧只有 `MainActivity.kt` 一个文件，且无 Channel 注册 | `apps/mobile/android/app/src/main/kotlin/com/zhaoxi/app/MainActivity.kt`（`class MainActivity : FlutterFragmentActivity()`） |
| flutter 无标准 APK 安装 API | 需端侧原生：`MethodChannel` + FileProvider + 系统安装 Intent |

### 2.2 Android 侧：两个硬阻断项

| 事实 | 证据 |
|---|---|
| **未声明 `REQUEST_INSTALL_PACKAGES`** | `AndroidManifest.xml:4-18` 权限仅 `READ_MEDIA_IMAGES` / `READ_MEDIA_VIDEO` / `READ_EXTERNAL_STORAGE` / `ACCESS_*_LOCATION` / `INTERNET` / `POST_NOTIFICATIONS` / `SCHEDULE_EXACT_ALARM` / `READ_MEDIA_VISUAL_USER_SELECTED` |
| **无任何 `<provider>` / FileProvider** | `AndroidManifest.xml:19-55`（`<application>` 内只有 `meta-data` 与 `<activity>`） |
| `applicationId = com.zhaoxi.app`；dev flavor 有 `.dev` 后缀 | `android/app/build.gradle.kts:28`、`:46-57`（`applicationIdSuffix = ".dev"`、`manifestPlaceholders["app_name"]`） |
| `versionCode` / `versionName` 均来自 flutter（即 `pubspec.yaml:4`） | `android/app/build.gradle.kts:31-32` |
| release 签名缺 `key.properties` 时**静默回退 debug 签名** | `android/app/build.gradle.kts:59-67`（注释点名 `PLT-005`）；`self-distribution-guide.md:111` 要求出包后必须核对签名指纹 |
| `minSdk = 26`（Android 8.0 起） | `android/app/build.gradle.kts:29` |

> **结论**：不落地 §5.5 的三件事（权限 + FileProvider + 前台安装 Intent），应用内安装在新机型上**必然失败**。这是本域最高优先级的改造点。

### 2.3 后端：无版本服务、无制品托管

| 事实 | 证据 |
|---|---|
| 路由汇总处无任何 version / release 模块 | `app/api/v1/router.py:20-36`（`chat/debug/feishu/history/llm/proactive/governance/ledger/tasks/insights/memory/home/briefing/car/auth`）；`android-store-release-guide.md:250` 已登记该结论 |
| 无版本/发布/更新类接口与表 | 搜索 `app_version` / `/release` / `apk` / `force_update` 命中全为业务词（规划重规划、`upgrade_requirements` 等） |
| 无对象存储 / 上传能力 | 搜索 `StaticFiles` / `UploadFile` / `minio` / `oss2` / `boto3` / `s3` 仅命中 `uv.lock` 与测试；唯一 `StaticFiles` 在 `scripts/serve_with_frontend.py:12,24`（前端 `dist`） |
| `console` 服务**无任何卷挂载** | `docker-compose.yml:33-49`（只有端口与 `env_file`；`volumes:` 段 `docker-compose.yml:51-52` 仅 `asuna_pgdata`） |
| Dockerfile 运行目录 `/srv/backend` | `Dockerfile:14`（`WORKDIR /srv/backend`）、`:17-20`（拷 `alembic.ini` / `app` / `migrations` / `scripts`）、`:25`（`alembic upgrade head` → `serve_with_frontend.py`） |
| 迁移链尾 `0008` | `apps/backend/migrations/versions/0008_ledger_categories_aliases_encoding.py`（`revision="0008"`）；钉测 `tests/support/schema_pins.py:13` `MIGRATION_HEAD = "0008"` |
| 迁移目录是 `migrations/`（**不是** `alembic/`） | `apps/backend/alembic.ini:8`（`script_location = %(here)s/migrations`） |
| ORM 模型**不在** `app/models/`，在 `app/core/db/` 领域子模块 | `app/core/db/__init__.py:1-5`（包门面注释：全部模型子模块必须在此导入）；`app/models/` 只放 Pydantic 域模型 |

### 2.4 ★ 合规底线冲突（本域最容易被忽略的一条）

`self-distribution-guide.md:122` 登记合规底线 1：

> **首启隐私弹窗**：未点「同意」前不得申请权限、不得初始化采集 SDK、**不得发起业务网络请求** —— 现状「⬜ 未实现（`apps/mobile/lib/app/bootstrap.dart:19-50` 无同意门控）」。

**冲突**：本域最自然的实现是「在 `bootstrap()` 里发起版本查询」。若那样做，一旦 `PLT-002` 落地同意门控，更新检查会**先于同意**发请求，直接违反底线 1。

**裁决（D3，见 §11）**：**更新检查不在 `bootstrap()` 内发起**。自动检查的触发点定在**首帧渲染后的 `app/` 装配层**（`UpdateGate`），它天然位于「同意门控之后、用户已进入应用之后」。这样：① 现在就能工作；② `PLT-002` 落地门控后**无需改 APP-044**，因为同意弹窗必然在首帧之前拦截。

> 不在本期范围：首启隐私弹窗本体（归 `PLT-002` / 上架指南 §7，`self-distribution-guide.md:144`）。

---

## 3. 端到端链路

### 3.1 链路图

```text
发布侧（PLT-008）
  flutter build apk --flavor prod --target-platform android-arm64
    → zhaoxi-<versionName>+<versionCode>-prod.apk
    → sha256 + apksigner 签名指纹 + 体积
    → 归档到制品目录 {storage}/{channel}/{versionCode}/
    → release-manifest.json（版本元数据）
    → 写入/更新 release 表（API-022 的表）

服务侧（API-022）
  GET /api/v1/app-release/latest?platform=android&channel=prod&version_code=12
  GET /api/v1/app-release/artifacts/{id}/download        （支持 Range）

客户端（APP-044）
  首帧后 / 手动「检查更新」
    → 读本地 versionCode（package_info_plus）
    → 查 latest
    → 版本比对（只认 versionCode）
    → 策略裁决 force | recommend | ignore
    → 弹层（A41 sheet 规格）
    → 下载（Dio 流式写盘 + Range 续传 + 进度回调）
    → 双校验（sha256 + 签名指纹）
    → MethodChannel installApk(path)
    → 系统安装器（FileProvider content:// + ACTION_VIEW）
    → 结果回收（下次启动比对已安装 versionCode）
```

### 3.2 版本号真相链（单向派生，禁止双写）

```text
pubspec.yaml:4   version: 0.1.0+1
        │
        ├─ Android: build.gradle.kts:31-32  versionCode = flutter.versionCode
        │                                   versionName = flutter.versionName
        ├─ iOS:     Runner/Info.plist:21-26 CFBundleShortVersionString = $(FLUTTER_BUILD_NAME)
        │                                   CFBundleVersion          = $(FLUTTER_BUILD_NUMBER)
        │
        ├─ 客户端读回: package_info_plus  → versionCode（比对基准，整数）
        ├─ 发布侧写入: PLT-008 从**产物**反读 versionCode → release 表
        └─ 服务端下发: latest.version_code
```

**纪律**：`versionCode` 是**唯一比对口径**，`versionName` 只用于展示。理由：`versionName` 允许回退/自定义（`0.2.0` 既可能是新版本，也可能是热修补的旧线），字符串比较无法判断新旧；`versionCode` 是整数且 `self-distribution-guide.md:109` 已把它定为「必须单调递增」的发布纪律，天然可比较。

### 3.3 更新状态机（端侧三态 × 三档策略）

```text
状态（UpdateState）
  idle → checking → upToDate
                  → available(strategy)  → downloading(progress) → verifying
                                          → readyToInstall        → installing → installed
                  → failed(reason)       ←（任何一步失败可重试）
                  
策略（UpdateStrategy）
  force      最低支持版本之上被跨越 / 服务端 force_update=true  → 弹层不可关闭，仅「立即更新」
  recommend  force_update=false 且 version_code > 本地         → 可「稍后再说」（本次会话不再提示）
  ignore     用户点「忽略此版本」                              → 写入 prefs，同一 versionCode 不再提示
```

**force 的判定条件（服务端唯一裁决，客户端不猜）**：

| 条件 | 判定 |
|---|---|
| `latest.version_code <= 本地 version_code` | **无更新**（`has_update:false`） |
| `本地 version_code < latest.min_supported_version_code` | **force**（已低于最低支持版本，必须升） |
| `latest.force_update == true` | **force** |
| 其余 | **recommend** |

---

## 4. 接口契约

### 4.1 `GET /api/v1/app-release/latest`

| 方向 | 字段 | 类型 | 必填 | 语义 / 缺省 |
|---|---|---|---|---|
| 请求 | `platform` | `string` | 是 | 取值域 `android` / `ios`；非法 → `422`。本期客户端固定传 `android`（`ios` 为语义位，无制品时返回 `has_update:false`） |
| 请求 | `channel` | `string` | 是 | 取值域 `dev` / `prod`；非法 → `422`。与客户端 `AppEnv.flavor`（`app_env.dart:10`，默认 `dev`）一一对应 |
| 请求 | `version_code` | `int` | 是 | 客户端当前已安装的 versionCode；`<= 0` → `422` |
| 响应 | `has_update` | `bool` | — | **无更新时 `false`**，且 `latest` / `artifacts` 为 `null` / `[]` |
| 响应 | `latest.version_name` | `string` | — | 展示用（如 `0.2.0`） |
| 响应 | `latest.version_code` | `int` | — | 比对口径 |
| 响应 | `latest.min_supported_version_code` | `int` | — | 低于此值 → force（§3.3） |
| 响应 | `latest.force_update` | `bool` | — | 服务端显式强制位 |
| 响应 | `latest.release_notes` | `string` | — | 纯文本，**≤ 2000 字符**；客户端不得渲染 HTML/Markdown（防注入） |
| 响应 | `latest.published_at` | `string` | — | ISO-8601 UTC |
| 响应 | `artifacts` | `array` | — | 见 §4.3；无更新时为 `[]` |

**错误语义**：`422` 非法 `platform` / `channel` / `version_code`；**无匹配发布记录 → `200` + `has_update:false`**（不是 404，不是 500）；**不透传堆栈**。

**裁决 D1：无更新返回 `200 + has_update:false`，不用 `204`。** 理由：客户端需要稳定结构驱动三态状态机（有更新 / 无更新 / 检查失败）；`204` 空体会让「无更新」与「服务端异常」在 Dio 层难以区分（`dio_client.dart:37-42` 的 `ErrorMappingInterceptor` 只处理错误态）。对齐 `API-010.md` §4.1 的既有裁决「无数据 → 200 + 空结果，不 500」。

**裁决 D2：该端点不鉴权。** 理由：① 版本查询是**冷启动路径**，不能依赖 token（`bootstrap.dart:28-29` 读 token 在 `appTokenStore`，未登录用户也须能收到安全更新）；② 无用户隐私数据；③ 与 `/health`（`main.py:169-171`）同级。**下载端点同理不鉴权**（见 §4.2），但**必须防目录穿越**。

### 4.2 `GET /api/v1/app-release/artifacts/{id}/download`

| 方向 | 字段 | 类型 | 必填 | 语义 / 缺省 |
|---|---|---|---|---|
| 路径 | `id` | `string` | 是 | 制品行主键（§6.1）；不存在 → `404` |
| 请求头 | `Range` | `string` | 否 | 标准 `bytes=<start>-`；服务端返回 `206 + Content-Range`，**断点续传依赖此** |
| 响应头 | `Content-Length` | `int` | — | 全量长度（`200`）或本次片段长度（`206`） |
| 响应头 | `Accept-Ranges` | `string` | — | 固定 `bytes` |
| 响应头 | `X-Artifact-Sha256` | `string` | — | 便于客户端/脚本核验（正式校验仍以 latest 下发的 `sha256` 为准） |
| 响应体 | 文件流 | `bytes` | — | 实现用 `FileResponse`（零拷贝友好，不整文件读入内存） |

**错误语义**：`404` 制品行不存在**或落盘文件缺失**（后者记 ERROR 日志并返回 `404`，不暴露路径）；`416` Range 越界。

**裁决 D4：下载路径由 `id` 反查存储路径，客户端不得传路径。** 理由：任何接受客户端路径的接口都是目录穿越入口。服务端必须做 `Path.resolve()` 后校验「结果仍在 `app_release_storage_dir` 之下」，否则 `403`。

### 4.3 ★ `artifacts[]` 契约与 patch 预留语义

```text
artifacts: [
  {
    "id": "art_...",                  // 制品行 id → 下载路径参数
    "type": "full",                   // 全量包；未来新增 "patch"
    "url": "/api/v1/app-release/artifacts/art_.../download",
    "size_bytes": 24000000,
    "sha256": "…",
    "signature_fingerprint": "…",     // SHA-256 指纹，大写冒号分隔，与 apksigner 输出同形
    "from_version_code": null         // patch 专用：基线版本号；full 恒 null
  }
]
```

**客户端处理纪律（fail-closed，对齐后端 `EXPECTED_EVENT_TYPES` 纪律 `tests/v30/test_runtime_contracts.py:27-42`）**：

1. 只处理 `type == "full"`；多个 `full` 时取**第一个**并记 WARN。
2. 遇到未知 `type`（含未来的 `patch`）→ **忽略该条并记 WARN，不回退、不猜测**；若因此无可用制品，则本次更新按 `failed(noApplicableArtifact)` 处理并降级为「提示用户手动到发布页下载」。
3. `sha256` / `signature_fingerprint` / `size_bytes` 任一缺失或非法 → **视为该制品不可用**（不跳过校验）。

**裁决 D5：用数组而非单字段。** 理由：未来接差分时只需**新增 `type` 取值**，契约结构、客户端解析路径、服务端表结构全部不动——这是「预留 patch 字段」诉求的唯一低成本落法。

### 4.4 渠道隔离

| 客户端 | 请求 `channel` | 服务端表内 `channel` | 后果 |
|---|---|---|---|
| `prod` flavor（`com.zhaoxi.app`） | `prod` | `prod` | 收到线上包 |
| `dev` flavor（`com.zhaoxi.app.dev`） | `dev` | `dev` | 只收到内测包 |

**裁决 D6：`channel` 必填且必须精确匹配，不做「prod 回退到 dev」之类的兜底。** 理由：内测包被推给线上用户是**不可逆事故**（用户装到一半的包可能不兼容数据格式）；`self-distribution-guide.md:101` 已记录 dev 包指向 `127.0.0.1` 的装机事故先例。

**裁决 D7：`dev` flavor 只检测不安装。** 理由：避免开发机被线上包覆盖；同时 dev 包常与本地后端联调，真实安装会打断调试。落法：`APP-044` 在 `dev` flavor 下把「立即更新」按钮替换为「前往发布页下载」文案（`A12 chip-btn ghost`），并**不下载、不安装**。此项写入 `APP-044` 的 Out of Scope 边界说明。

---

## 5. 客户端设计

### 5.1 模块边界：`lib/core/updater/`

```text
lib/core/updater/
├── release_api.dart        // 只做 HTTP：latest / download（流式）；返回 DTO
├── release_models.dart     // ReleaseInfo / ReleaseArtifact / UpdateCheckResult（手写 final class，不上 Freezed）
├── update_checker.dart     // 版本比对 + 策略裁决（纯函数，可单测）
├── apk_downloader.dart     // Dio 流式写盘 + Range 续传 + 进度 + sha256
├── apk_verifier.dart       // sha256 + 签名指纹比对
├── apk_installer.dart      // MethodChannel 封装（installApk / canInstallPackages / openInstallPermissionSettings / installedVersionCode）
└── update_providers.dart   // Riverpod：updateStateProvider / updatePrefsProvider

lib/app/update/                       // 装配层：可同时 import core/ 与 design_system/
├── update_gate.dart        // 首帧后触发 + 24h 节流 + 残留清理 + 安装结果回收（★ 不在 bootstrap 内，§5.2）
└── update_sheet.dart       // A41 规格更新面板（force / recommend / 下载中 / 失败 / 拒权 五态）
```

**分层纪律（对齐 `flutter-architecture.md:196-198` 与 `tasks/README.md:98`）**：

| # | 纪律 |
|---|---|
| L1 | `core/updater/` **不得** import 任何 `features/*`；UI 由 `features/profile` 与 `app/` 消费它 |
| L2 | `core/updater/` **不得** import `design_system/`（设计系统不得反向依赖 `core/`，反向亦然——`flutter-architecture.md:197`） |
| L3 | 网络调用只经 `release_api.dart`，不在 `features/*/presentation` 直接调 dio（`flutter-architecture.md:198`） |
| L4 | `features/profile` 与 `app/` 之间零新增 import（更新弹层的挂载由 `app/` 装配层完成，见 §5.6） |

**裁决 D8：模型不用 Freezed。** 理由：`flutter-architecture.md:46` 的反向建议——「只在需要 union / 深度相等 / JSON 三者之一成立时才用 Freezed」。本域三个模型都无 union，手写 `final class` + `fromJson` 约 15 行/个，省掉一次 build_runner 往返。

### 5.2 触发时机与节流

| 触发 | 时机 | 节流 | 依据 |
|---|---|---|---|
| 自动检查 | **首帧渲染后**（`app/` 装配层的 `UpdateGate`），不在 `bootstrap()` 内 | 距上次检查 ≥ **24h**；`dev` flavor 同规则 | §2.4（合规底线 1）；D3 |
| 手动检查 | 我的页「检查更新」行 / 关于页「检查更新」按钮 | **不受节流限制** | 用户显式动作 |
| 重试 | 下载失败后由用户点「重试」 | 不自动重试（避免后台流量） | D9 |

**裁决 D9：下载失败不自动重试。** 理由：APK 体量在 20–60 MB 量级，自动重试容易在弱网下形成流量黑洞；改为「保留已下载分片 + 用户点重试时走 Range 续传」，兼顾成本与体验。

### 5.3 下载与断点续传

| 项 | 契约 |
|---|---|
| 落盘位置 | 应用私有目录（`getApplicationSupportDirectory()` 下的 `updates/`），**不落外部存储**（免权限、免残留泄漏） |
| 分片 | 单文件写盘，不切片；续传靠 `Range: bytes=<已有长度>-` |
| 校验中断 | 续传前**不做** sha256 校验（未完整），仅在下载完成后整体校验 |
| 进度节流 | 进度回调按 **16ms 窗口合帧**（对齐 `flutter-architecture.md:228` 的「逐 token 重绘」处理思路），避免高频 setState 掉帧 |
| 清理 | 安装成功 / 校验失败 / 用户取消 → 立即删除临时文件；冷启动时无条件清空 `updates/` 目录下**非当前进行中**的残留 |
| 网络偏好 | 新增 prefs 键 `update.wifi_only`（默认 `true`）；移动网络下弹二次确认（`A41 choice-sheet`）后才开始 |
| 取消 | 页面 dispose / 用户点取消 → `CancelToken.cancel()`（`dio_client.dart` 已具备拦截器链，`CancelToken` 按 Dio 标准 API 使用） |

### 5.4 ★ 安全双校验链

```text
下载完成
  → ① 体积比对（size_bytes）
  → ② sha256 比对（与 latest.artifacts[].sha256 逐字节一致）
  → ③ 原生侧读 APK 签名指纹（PackageManager.getPackageArchiveInfo + GET_SIGNING_CERTIFICATES）
       与「当前运行 App 的签名指纹」比对，必须一致
  → 全部通过 → 进入安装；任一失败 → 删除文件 + failed(reason) + 可重试
```

**为什么必须做 ③**：sha256 只能证明「文件与清单一致」，不能证明「这个包是同一个开发者签的」。若制品托管被替换（或镜像/代理投毒），攻击者可用自己的签名重打包并同步替换清单里的 sha256 —— 签名指纹比对才是**应用身份**的锚点（`self-distribution-guide.md:110` 已把签名定性为「应用身份」）。

**裁决 D10：签名指纹必须与「运行中的 App 自身签名」比对，不得只与清单里的 `signature_fingerprint` 比对。** 理由：后者与 sha256 同源（都来自服务端清单），无法抵御清单被篡改。

**debug 回退场景**：`build.gradle.kts:59-67` 允许 release 缺 `key.properties` 时回退 debug 签名 → 同一台机器上「debug 包更新 debug 包」的指针比对仍成立；但**跨签名更新会失败**（这是正确行为，不是缺陷）。`PLT-008` 必须在发布前核对签名指纹并在 manifest 落库（`self-distribution-guide.md:111`）。

### 5.5 安装链路（原生契约）

```text
MethodChannel: "com.zhaoxi.app/updater"
  installApk(apkPath: String) -> Boolean            // 校验通过后调起系统安装器；返回「是否成功调起」
  canInstallPackages() -> Boolean                   // 是否已授予「安装未知应用」
  openInstallPermissionSettings() -> void           // 拒权时跳系统设置页
  installedVersionCode() -> Int                     // 读回已安装版本，用于结果回收
  signatureFingerprint(apkPath: String) -> String?  // 读 APK 签名指纹（§5.4 ③）
```

| 项 | 契约 | 理由 |
|---|---|---|
| FileProvider authority | **`${applicationId}.fileprovider`**（manifest placeholder 形式） | dev flavor 有 `.dev` 后缀（`build.gradle.kts:46-57`），写死常量会导致 dev/prod 同机安装冲突（authority 重复注册或解析到错误 App） |
| FileProvider 路径 | `res/xml/file_paths.xml` 暴露 `<cache-path>` 或 `<files-path>` 下 `updates/` 子目录，**不得暴露整个存储** | 最小暴露面 |
| 安装 Intent | `ACTION_VIEW` + `setDataAndType(uri, "application/vnd.android.package-archive")` + `FLAG_GRANT_READ_URI_PERMISSION` | Android 7.0+ 的 `content://` 标准姿势 |
| 权限 | 新增 `<uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES" />` | Android 8.0+ 必需（`minSdk = 26`，`build.gradle.kts:29`） |
| 拒权引导 | `canRequestPackageInstalls()` 为 false → 弹层引导 + `ACTION_MANAGE_UNKNOWN_APP_SOURCES` 跳设置页 | 现状无任何引导路径 |
| **前台要求** | 安装必须在 **Activity 前台**发起；不得在后台/服务里调 | Android 10+ 后台启动 Activity 受限；Android 14（API 34）进一步收紧，后台无法拉起安装器 |
| 结果回收 | 主路径 = **下次冷启动比对 `installedVersionCode()`**；辅路径 = 安装器返回后重新读一次 | `ACTION_PACKAGE_REPLACED` 广播在部分 ROM 上不可靠，不作为唯一依据 |
| 频道注册点 | `MainActivity.kt`（已继承 `FlutterFragmentActivity`，可承载 Channel 与权限跳转） | `MainActivity.kt` 现状仅 1 个 class 声明 |

**裁决 D11：不做安装结果实时回调的复杂态机**，只保留「下次启动比对」。理由：安装过程中用户会离开 App（系统安装器全屏），Flutter 侧状态在 `onStop`/`onResume` 之间不可靠；用「冷启动比对已安装 versionCode」这一个确定信号收口，比追逐广播更稳。

### 5.6 UI 落点（设计系统为唯一真源）

| 落点 | 组件 | 规格引用 |
|---|---|---|
| 更新弹层 | **`A41` 底部面板规格**（离屏 12 浮起 · 圆角 `rLg` · 白底 + 柔和投影 · 把手 38×4 色 `line` 居中 · 标题 16.5px/700） | `components.md:504-528` |
| 「立即更新」按钮 | **`A32 save`**（满宽 · 底 `ink` · 字白 15px/700 · 圆角 `rFull` · 内边距 15 · 投影） | `components.md:366-371` |
| 「稍后再说」按钮 | **`A32 save-pair` 的次级按钮**（底 `surface` · `line` 描边 1px · 字 `ink2` 15px/700 · `rFull`） | `components.md:366-371` |
| 下载进度 | 自绘进度条（高 7 · 圆角 `rFull` · 轨道 `trackBar` · 填充 `barBlue`）——**不要用 `barMoney`**（财务语义） | `tokens.md:134`、`components.md:79-80` |
| 我的页入口行 | **`A26 set-row`**（`SettingRow`：`title` / `subtitle` / `icon` / `iconBg` / `iconColor` / `trailing` / `onTap` / `showDivider`） | `rows.dart:184-252`；先例 `profile_page.dart:422-435` |
| 关于页 | 从设置页 push 的子页面，**沿用 `AppBar(title: Text('关于'))` + `SettingGroup`** 的既有形态；页面结构编号需**先在 skill 登记为 `B20 #about`**（skill 现为 `B1~B19`，无此页）——这是承接 `self-distribution-guide.md:139` 已登记的缺口，不是发明需求；备案号 / 软著名公示位**只留位不填值**（内容归 `PLT-002`） | 先例 `privacy_page.dart:17-22`（`AppBar` + `ListView(padding: fromLTRB(18, 8, 18, 40))`）；回写要求见 §12 回写项 4 |
| 版本行 | 文案沿用 skill 既有范例句式：**「朝夕 v<versionName> · Personal AI OS 的第一步」**（把 `principles.md:95` 的硬编码版本号替换为真值） | `principles.md:95`；`components.md:728`（B8 第 6 段：居中 13px `ink2`） |
| 数字 | 版本号 / 下载百分比 / 体积全部走 **`AppTypography.numeric`**（等宽） | `tokens.md:193`、`flutter-mapping.md:76-80` |

**裁决 D12：用底部面板（`A41` 规格），不用系统 `AlertDialog`。** 理由：① skill 内**没有**通用 Modal / AlertDialog 规范（已核实：全目录检索仅命中 `A41` 底部面板）；② 更新弹层需要承载「更新说明滚动区 + 进度条」两块内容，`AlertDialog` 的尺寸约束不适合；③ `A41` 既有规范的把手 / 圆角 / 按钮位置可直接复用，且其纪律「面板自己让开软键盘」「内容块 `mainAxisSize.min`」（`components.md:510-513`）已被验证过。

**裁决 D13：强制更新弹层的确认键取 `ink` 深色，禁用 `ai` 渐变**（`A32` 与 `A41` 双处纪律：`components.md:371`、`components.md:523`）。理由：下载安装是**用户动作**，不是 AI 行为；`ai` 渐变在本设计系统里只表示「AI 的存在与行动」（`tasks/README.md:68` 红线）。

**文案纪律**：`principles.md:77-95` 为文案真源，其中**唯一**与版本相关的范例是版本行（`principles.md:95`）。更新弹层的其余文案（标题 / 说明 / 按钮）**没有既有范例**，必须按 `principles.md:67-75` 的语气规则自拟并回写 skill（见 §9 风险 5）：用「我在准备新版本，装好后就能用上了」而非「检测到新版本，请立即升级」；不说「系统检测到」（`principles.md:68`）；不用「必须 / 请立即」（`principles.md:69`）。

### 5.7 prefs 键名（须同步登记 `PrefsStore.allKeys`）

| 键 | 类型 | 语义 |
|---|---|---|
| `update.last_check_at` | `int`（毫秒） | 上次成功检查时间（节流依据） |
| `update.ignored_version_code` | `int` | 用户忽略的 versionCode（同一版本不再提示） |
| `update.wifi_only` | `bool`（默认 `true`） | 仅 Wi-Fi 下载 |

**约束**：`PrefsStore` 的键名惯例为「域.蛇形名」，且 `allKeys`（`prefs_store.dart:17-27`）是键登记表，**新增键必须同步登记**（`test/scaffold/` 有集中化守卫测试）。**禁止**把版本号 / 下载进度 / sha256 写进 prefs（`prefs_store.dart:3` 明令「只存参数类值」）。

---

## 6. 后端设计

### 6.1 数据面：`app_releases` + `app_release_artifacts`

**裁决 D14：两表（发布记录 + 制品），不是单表。** 理由：`artifacts[]` 是多值结构（§4.3），塞进单表只能靠 JSON 列或重复行；两表让「一个版本可挂多个制品（未来 full + patch 并存）」成为自然表达，且下载端点有稳定的行主键可寻址。

| 表 | 字段 | 类型 | 约束 |
|---|---|---|---|
| `app_releases` | `id` | `String` | 主键（经 `app/core/ids.py` 发号，对齐 `identity.py` 的 `String` 主键惯例） |
| | `platform` | `String` | `NOT NULL`；`CHECK (platform IN ('android','ios'))` |
| | `channel` | `String` | `NOT NULL`；`CHECK (channel IN ('dev','prod'))` |
| | `version_name` | `String` | `NOT NULL` |
| | `version_code` | `Integer` | `NOT NULL` |
| | `min_supported_version_code` | `Integer` | `NOT NULL`；`CHECK (min_supported_version_code >= 0)` |
| | `force_update` | `Boolean` | `NOT NULL`，`server_default = "false"` |
| | `release_notes` | `Text` | `NULL` |
| | `published_at` | `UtcDateTime` | `NOT NULL` |
| | `created_at` / `updated_at` | `UtcDateTime` | `NOT NULL`（`identity.py:27-28` 惯例） |
| | 唯一性 | | `UniqueConstraint(platform, channel, version_code)` |
| | 索引 | | `Index("ix_app_releases_lookup", "platform", "channel", "version_code")` |
| `app_release_artifacts` | `id` | `String` | 主键 |
| | `release_id` | `String` | `NOT NULL` + 外键 → `app_releases.id` |
| | `artifact_type` | `String` | `NOT NULL`；`CHECK (artifact_type IN ('full','patch'))` |
| | `from_version_code` | `Integer` | `NULL`（`full` 恒 `NULL`；`patch` 写基线版本号） |
| | `storage_path` | `String` | `NOT NULL`（**相对** `app_release_storage_dir` 的路径，不存绝对路径） |
| | `size_bytes` | `Integer` | `NOT NULL`；`CHECK (size_bytes > 0)` |
| | `sha256` | `String(64)` | `NOT NULL` |
| | `signature_fingerprint` | `String` | `NULL`（`ios` 制品可空） |
| | `created_at` | `UtcDateTime` | `NOT NULL` |

**裁决 D15：`artifact_type` 的 CHECK 里**预置** `'patch'`，但本期无写入路径。** 理由：与 §4.3 的「预留 patch 契约」同源——约束层先容纳未来取值，避免将来接差分时**必须改迁移**。这是「预留」在数据面的唯一落点；除此之外**不留任何死字段**（`rollout_percent` 之类一律不建，见 §1.2）。

**裁决 D16：不建「当前有效版本」布尔位。** 理由：「最新版本」= `(platform, channel)` 分组下 `version_code` 的最大值，是**查询可得的派生量**；加 `is_active` 之类布尔位会引入第二真相源与更新时序问题（旧版本发布时还要回头关掉新版本），且与全局约束「不新增功能位」同向。

### 6.2 迁移 `0009` 与钉测升级清单

| 项 | 值 | 证据 |
|---|---|---|
| 迁移目录 | `apps/backend/migrations/versions/` | `apps/backend/alembic.ini:8`（`script_location = %(here)s/migrations`） |
| 链尾现状 | `0008_ledger_categories_aliases_encoding.py` | `tests/support/schema_pins.py:13`（`MIGRATION_HEAD = "0008"`）、`:14`（`MIGRATION_HEAD_PARENT = "0007"`） |
| 本任务新增 | `0009_app_release_artifacts.py`（`revision="0009"`、`down_revision="0008"`）；表数 55 → **57**（**加两张表**） | `tests/support/schema_pins.py:16`（`SCHEMA_TABLE_COUNT = 55`） |
| 表数增量 | **+2**（`app_releases` + `app_release_artifacts`） | §6.1 D14 |
| HEAD 口径 | 链尾 ⇒ 新的 `MIGRATION_HEAD = "0009"`、`MIGRATION_HEAD_PARENT = "0008"` | — |

**迁移纪律三陷阱（逐条留痕，对照 `tasks.md` §0.3）**：

| # | 陷阱 | 本任务处置 |
|---|---|---|
| 1 | **链尾/钉测常量** | 按上表逐项 bump；`SCHEMA_COLUMNS_DIGEST` **必须实测回填**（先实现迁移 → 跑一次 `schema_columns_digest()` 取实际摘要 → 回填），**禁止手算** |
| 2 | **CHECK 布尔式** | 全部写成**完整布尔表达式**传参（如 `"platform IN ('android', 'ios')"`），**禁止传值元组**（历史代价：PG 上 `DatatypeMismatch`、`downgrade` 不可达） |
| 3 | **钉测升级清单** | 见下表；另须过 `tests/unit/test_datetime_discipline.py:84-90`（新增迁移**不得**出现裸 `timezone=True`，一律走 `UtcDateTime`） |

**钉测升级清单（逐文件）**：

| # | 文件 | 具体改动 |
|---|---|---|
| 1 | `apps/backend/tests/support/schema_pins.py` | `MIGRATION_HEAD` `"0008"`→`"0009"`；`MIGRATION_HEAD_PARENT` `"0007"`→`"0008"`；`SCHEMA_TABLE_COUNT` `55`→`57`；`SCHEMA_COLUMNS_DIGEST` 重算（该文件 `:5` 自述「升级迁移时只改本模块 + 迁移文件本身，目标改动文件数 ≤ 3」） |
| 2 | `apps/backend/tests/v51/test_car_schema.py:51` | 硬编码 `== SCHEMA_TABLE_COUNT == 55` 的 `55` → `57`（全仓唯一一处硬编码表数断言） |
| 3 | `apps/backend/tests/v24/tool012_support.py:74-82` | `INCREMENTAL_MIGRATION_FILES` 追加 `"0009_app_release_artifacts.py"`（登记性常量，已核实无测试消费） |
| 4 | 新增 `apps/backend/tests/v50/test_app_release_schema.py` | ORM 列 / 索引 / CHECK / 链头 / 表数 / 正逆放（`downgrade` 可达） |

**无需改动（已用 pin，自动跟随）**：`tests/v40/test_*`、`tests/v30/test_runtime_migration_0052.py`、`tests/v40/test_life_migration_0053.py` 等均 import pin 后断言，故只需上表 1~3。

**ORM 注册（非测试，但会导致 `Base.metadata` 不完整）**：新模型必须在 `apps/backend/app/core/db/__init__.py` 的 import 段与 `__all__` 段**双处登记**（该文件 `:3-4` 注释：「全部模型子模块必须在此导入，保证 `Base.metadata` 完整」）。

### 6.3 制品存储

| 项 | 契约 |
|---|---|
| 设置项 | **`app_release_storage_dir`**（`string`，参数类，无 `*_enabled`；env 名 = `APP_RELEASE_STORAGE_DIR`，无 alias 层） |
| 默认值 | Docker 内 `/srv/backend/releases`；本地开发默认 `apps/backend/.tmp/releases` |
| 目录布局 | `{storage_dir}/{channel}/{version_code}/{artifact_type}/` |
| Compose 挂载 | `docker-compose.yml` 的 `console` 服务**需新增卷挂载**（现状该服务无任何 volumes，见 `docker-compose.yml:33-49`）→ 新命名卷 `asuna_releases:/srv/backend/releases`，并在 `volumes:` 段（`docker-compose.yml:51-52`）登记 |
| 缺失行为 | 启动时目录不存在 → **不自动创建、不报错**（无发布记录时属正常态）；下载时文件缺失 → `404` + ERROR 日志 |
| 安全 | 服务端解析路径后必须校验「结果仍在 `storage_dir` 之下」（§4.2 D4） |

### 6.4 后端设置项

新增 `apps/backend/app/core/settings/app_release.py`：`class AppReleaseSettings(BaseSettings)`，`model_config = DOMAIN_MODEL_CONFIG`，并加入 `app/core/settings/__init__.py` 的 `Settings` 组合类（`__init__.py:47-79`）。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `app_release_storage_dir` | `string` | 见 §6.3 | 制品根目录 |
| `app_release_notes_max_chars` | `int` | `2000` | 更新说明长度上限（超出 → `422`，见 §4.1） |

**纪律**：均为**参数类**字段（`tasks/README.md:93`）；env 名 = 字段名大写（`APP_RELEASE_STORAGE_DIR`）；**不带 `vXX_` 前缀**（AGENTS.md 全局约定）；须同批更新 `apps/backend/.env.example`。

---

## 7. 发布侧设计（PLT-008）

### 7.1 制品命名与归档

沿用 `self-distribution-guide.md:112` 已登记的命名规范，**不新造第二套**：

```text
zhaoxi-<versionName>+<versionCode>-<flavor>.apk
  → 归档: {app_release_storage_dir}/{channel}/{version_code}/full/
  → 同目录落 release-manifest.json
```

### 7.2 `release-manifest.json`（PLT-008 → API-022 的交接物）

| 字段 | 类型 | 来源 |
|---|---|---|
| `platform` | `string` | 固定 `android`（脚本入参） |
| `channel` | `string` | 脚本入参（`dev` / `prod`） |
| `version_name` | `string` | **从产物反读**（`aapt dump badging` 或 `package_info`），**不从 `pubspec.yaml` 文本解析** |
| `version_code` | `int` | 同上（保证「客户端读到的新版本号」与「制品实际版本」同源） |
| `min_supported_version_code` | `int` | 脚本入参（发布决策） |
| `force_update` | `bool` | 脚本入参（发布决策） |
| `release_notes` | `string` | 脚本入参（文件路径或直接文本） |
| `artifact.type` | `string` | 固定 `full`（本期） |
| `artifact.size_bytes` | `int` | 脚本实测 |
| `artifact.sha256` | `string` | 脚本实测 |
| `artifact.signature_fingerprint` | `string` | `apksigner verify --print-certs` 输出 |

**裁决 D17：`version_code` / `version_name` 从 APK 反读，不从 `pubspec.yaml` 解析。** 理由：`pubspec.yaml` 与产物之间存在 flavor / 构建参数 / 手工覆盖三层可能偏差；反读是唯一「制品即真相」的做法，也是 §3.2 版本真相链的收口点。

### 7.3 与 `PLT-005` 的边界（必须留痕，防职责重叠）

| 任务 | 负责 | 不负责 |
|---|---|---|
| `PLT-005`（`tasks.md:222`，未开工） | `flutter build` 出**签名 APK**（flavor 隔离、密钥不进仓库、R8、CI 门禁、`.github/workflows/*`） | 版本元数据、制品归档布局、sha256 / 签名指纹落库、manifest |
| `PLT-008`（本域） | APK → 制品目录布局 + sha256 / 签名指纹 + `release-manifest.json` + 版本元数据写入 `release` 表 | 构建、签名、密钥管理、CI 流水线定义 |

> **消费关系**：`PLT-008` **消费** `PLT-005` 的产物（签名 APK）与 `key.properties` 约定；`API-022` **消费** `PLT-008` 的 `release-manifest.json` 与目录布局。三者构成发布链，**无循环依赖**。

---

## 8. 测试策略

| 层 | 覆盖对象 | 方式 |
|---|---|---|
| 单元（客户端） | 版本比对与策略裁决（force / recommend / ignore 全分支）、`artifacts[]` 解析（未知 type → 忽略；缺 sha256 → 不可用）、sha256 计算 | `flutter_test` 纯 Dart |
| Golden（客户端） | 更新弹层三档（force / recommend / 下载中 / 失败）、我的页「检查更新」行、关于页版本行 | `matchesGoldenFile` |
| Widget（客户端） | 弹层可开可关、force 不可关、进度文案与百分比一致、拒权引导路径 | `flutter_test` + `mocktail` |
| 原生（Kotlin） | sha256 校验、签名指纹比对（含「与自身签名不一致」负例） | JVM 单测（`signatureFingerprint` 可注入 fixture APK） |
| 后端 Focused | 无更新返回 `has_update:false`；`min_supported_version_code` 触发 force；非法 `platform` / `channel` → `422`；未知 `id` → `404`；**目录穿越用例**（`id` 无法构造路径）；Range 请求 → `206` + `Content-Range` | `pytest tests/v50/test_app_release_*.py` |
| 后端 Module | 迁移链头 `0009` / 表数 / 正逆放；`app/api/v1/app_release.py` **零 `app.repositories` import**（AST 断言，先例 `API-010.md` §7.2） | — |
| 基线对照 | 零回归判据 = **当前失败集 ⊂ 基线失败集**（`tasks/README.md:103`） | `git stash` 对照法 |
| 真机集成 | 手动检查 → 下载 → 安装 → 冷启动版本号变化；拒权引导；断网续传 | 人工 + `integration_test` |

**关键约定**：`artifacts[]` 契约回放 fixture **必须包含**「未知 type」「缺 sha256」「`has_update:false`」「`force_update:true`」四种，这四条是最容易在真实环境出问题、又最难手工复现的路径（对齐 `flutter-architecture.md:393` 的 fixture 纪律）。

---

## 9. 风险与备选

| # | 风险 | 概率 | 影响 | 触发信号 | 应对 / 备选 |
|---|---|---|---|---|---|
| 1 | **Android 14+ 后台/前台限制**导致安装器拉不起 | 中 | 高 | 真机点「安装」无反应 | 安装一律在 Activity 前台发起；弹层负责说明「请保持应用在前台」；备选：改为「下载完成后跳系统文件管理器打开」 |
| 2 | **「安装未知应用」被拒**且用户不知道去哪开 | 高 | 中 | 用户反馈「装不上」 | `canRequestPackageInstalls()` 预检 + `ACTION_MANAGE_UNKNOWN_APP_SOURCES` 一键跳转；文案照 `self-distribution-guide.md:99` 的既有话术 |
| 3 | **跨签名更新失败**（分发过一次 debug 签名的包） | 中 | 高 | 安装报签名不一致 | `PLT-008` 出包必核签名指纹（`self-distribution-guide.md:111`）；客户端在 §5.4 ③ 提前拦截并给出「旧包需卸载重装」提示 |
| 4 | **制品被替换**（托管目录被写 / 代理投毒） | 低 | 极高 | sha256 或签名指纹不匹配 | §5.4 双校验链；签名指纹与「运行中 App 自身签名」比对（D10），而非只比清单 |
| 5 | **更新弹层文案无既有范例**，与设计系统语气冲突 | 高 | 低 | 人工走查不合格 | 按 `principles.md:67-75` 语气规则自拟；落地后**同批回写** skill（登记为待回写项） |
| 6 | **未上架状态下用自有通道分发**引发的合规问询 | 中 | 中 | 用户投诉「未经安全检测」 | `self-distribution-guide.md:100` 已有应对话术；`PLT-002` 统筹合规结论 |
| 7 | **大文件下载在弱网下的体验** | 高 | 中 | 进度长时间不动 | Range 续传 + 不自动重试（D9）+ 「仅 Wi-Fi」默认开 |
| 8 | **迁移打破跨版本钉测**（约 22 条） | 高 | 中 | 钉测批量转红 | 按 `tasks.md` §9 R3 的既有应对：先用 `git worktree` 测 blast radius，再按 §6.2 清单逐项升级 |
| 9 | **`SCHEMA_COLUMNS_DIGEST` 手算填错** | 中 | 中 | 钉测转红 | 强制「先实现迁移 → 实测取值 → 回填」，禁止手算（§6.2 陷阱 1） |
| 10 | **`app_release_storage_dir` 未挂卷导致容器重建后制品丢失** | 中 | 高 | 下载 404 | §6.3 的 compose 卷挂载为**硬项**，写入 `PLT-008` / `API-022` 验收 |

---

## 10. ★ 演进到增量更新的路径（只加 type，不改契约）

本期交付的契约已为差分预留完毕，接差分时**唯一需要改动的是新增一条 `artifact_type` 取值与端侧合成能力**：

| 步骤 | 改动面 | 是否改契约 |
|---|---|---|
| ① 服务端出补丁 | `PLT-008` 增加「对上一版本做 bsdiff/HDiffPatch → 产出 `patch` 制品」的出包步骤 | 否（表已容 `'patch'`，D15） |
| ② 元数据下发 | `artifacts[]` 里**追加**一条 `{type:"patch", from_version_code:N, ...}`；`full` 仍照常下发 | 否（数组结构不变，D5） |
| ③ 端侧选择 | 客户端按「本地 versionCode 命中 `from_version_code` 且有对应 patch」优先选 patch，否则回落 `full` | 否（本期已有 fail-closed 回落路径） |
| ④ 端侧合成 | 新增原生 `applyPatch(oldApkPath, patchPath) -> newApkPath`（MethodChannel 加一个方法） | 否（Channel 方法追加不破坏既有签名） |
| ⑤ 校验与安装 | **合成后的新 APK 走完全相同的 §5.4 双校验链**（sha256 与签名指纹都必须匹配 `full` 制品的口径） | 否（这是差分安全的关键：不能因为是补丁就跳过校验） |

**纪律**：③④⑤ 是**同一个任务**（不可拆成两个发布），因为「能合成但不能校验」= 可被投毒；「能校验但不能合成」= 无收益。

**明确不做的事**（避免演进时误加）：不做单版本多补丁矩阵的自动清理策略、不做补丁体积收益的埋点报表、不做「补丁失败静默回落全量」之外的任何降级猜测行为（失败必须明示并回到 `full`，且记录原因）。

---

## 11. 关键裁决汇总

| # | 裁决 | 理由（摘要） | 落点 |
|---|---|---|---|
| D1 | 无更新返回 `200 + has_update:false`，不用 `204` | 客户端需稳定结构区分「无更新」与「服务异常」 | §4.1 |
| D2 | 版本查询与制品下载**不鉴权** | 冷启动路径不可依赖 token；无隐私数据；与 `/health` 同级 | §4.1 / §4.2 |
| D3 | **自动检查不在 `bootstrap()` 内**，挂首帧后的 `app/` 装配层 | 合规底线 1「未同意不得发业务网络请求」；且 `PLT-002` 门控落地后无序改 | §2.4 / §5.2 |
| D4 | 下载路径由 `id` 反查，服务端强制校验在 `storage_dir` 之下 | 防目录穿越 | §4.2 |
| D5 | `artifacts[]` 用数组 | 未来接差分只加 `type` 取值，不改契约 | §4.3 |
| D6 | `channel` 必填且精确匹配，无兜底 | 内测包推给线上用户是不可逆事故 | §4.4 |
| D7 | `dev` flavor 只检测不安装 | 防开发机被线上包覆盖、防打断联调 | §4.4 |
| D8 | 客户端模型**不用 Freezed** | 无 union 需求；省一次 build_runner 往返 | §5.1 |
| D9 | 下载失败**不自动重试** | 避免弱网流量黑洞；改为保留分片 + 手动续传 | §5.2 |
| D10 | 签名指纹与**运行中 App 自身签名**比对，而非只比清单 | 清单与 sha256 同源，无法抵御清单被篡改 | §5.4 |
| D11 | 安装结果回收以「下次冷启动比对 versionCode」为准，不追广播 | 安装过程 App 离开前台，Flutter 态不可靠 | §5.5 |
| D12 | 更新弹层用 **`A41` 底部面板**，不用系统 `AlertDialog` | skill 无通用 Modal 规范；需承载滚动说明 + 进度条 | §5.6 |
| D13 | 确认键取 `ink` 深色，**禁 `ai` 渐变** | 下载安装是用户动作，非 AI 行为（设计系统红线） | §5.6 |
| D14 | 数据面用**两表**（发布 + 制品） | `artifacts[]` 是多值结构；为 full/patch 并存留出自然表达 | §6.1 |
| D15 | `artifact_type` 的 CHECK **预置 `'patch'`**，本期无写入路径 | 预留落点；避免将来接差分时必须改迁移 | §6.1 |
| D16 | 不建「当前有效版本」布尔位 | 派生量不应成为第二真相源；与「不新增功能位」同向 | §6.1 |
| D17 | `version_code` / `version_name` 从 **APK 反读** | 制品即真相；`pubspec.yaml` 与产物间存在多层偏差 | §7.2 |

---

## 12. 实施前置与回写清单

| # | 事项 | 归属 | 时机 |
|---|---|---|---|
| 1 | 更新基线 `docs/current-system-architecture-baseline.md`（新增域 + 迁移链尾 `0009`；该文档 `:529` 记有链尾现值） | `API-022` / `PLT-008` | **实施同批**（AGENTS.md：「任何架构演进须先更新该基线再进入开发」） |
| 2 | 回写 `tasks.md` §15.10 编号占用表（`APP-044` / `API-022` / `PLT-008` 由「下一可用号」转为实际占用） | 本文档登记批 | 本次已随 §1.3 登记，实施时回填 |
| 3 | 关闭 `tasks.md` §15.11 台账 #7 中的「打包脚本与版本端点」两项（`tasks.md:639`） | `PLT-008` / `API-022` | 实施完成时 |
| 4 | 回写 `.agents/skills/zhaoxi-design-system/`：① `references/components.md` **新增 `B20 #about` 页面结构登记**（skill 现为 `B1~B19`，无关于页；「skill 先登记、页面后落地」的顺序不可缺少）；② `references/principles.md` §5.3 新增更新弹层文案范例（本域文案在现版 §5.3 中**无范例**，仅版本行 `principles.md:95` 可沿用）；③ 版本行的 `(MVP)` 去留由设计侧裁决 | `APP-044` | **第 ① 项为开工前置**（不是完工后补）；② ③ 可与实现同批 |
| 5 | 回写 `profile_page.dart:509` 的版本行「真值化」结论到合规文档（`android-store-release-guide.md:244`、`self-distribution-guide.md:139` 的 ⬜ 项关账） | `APP-044` | 实施完成时 |
| 6 | `self-distribution-guide.md` §7 剩余缺口（`dart_defines/prod.json`、Web 目标定稿、首启隐私弹窗等 4 项）**不在本域**，保持待立任务状态 | — | 不在本期 |
| 7 | 既有文档多处以 `tests/v30/runtime_contracts.py` 简称引用该常量文件（`tasks.md:29`、`tasks/README.md:80`、多份 `API-0*.md`），但**该路径不存在**——实际为 `tests/v30/test_runtime_contracts.py`（已核实）。本批新文档一律使用真实路径；**既有文档是否统一订正另开裁决**（不在本批） | 全仓文档 | 不在本期 |
