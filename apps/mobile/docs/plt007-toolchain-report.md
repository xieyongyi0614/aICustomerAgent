# PLT-007 Flutter 工具链与相册依赖可行性报告

> **任务**：`docs/version/v5.0.0/tasks.md` §15.5 / `docs/version/v5.0.0/tasks/PLT-007.md`（三期硬门槛）
> **结论摘要（2026-09-30，2026-10-01 闭环更新）**：**命令行门槛与依赖面门槛均已解除** —— 三条命令真实可用；`photo_manager` 解析、构建与真机读相册 demo 三步全部通过（见 §7）。**三期（`APP-034~040` / `APP-043`）解除阻塞，可开工**。
> **日期**：2026-09-30（2026-10-01 补记 §7）｜ **状态**：**已完成**

---

## 1. 背景（原故障）

`reviews/progress-audit-2026-09-29.md` §7.7 记录：本机 `flutter pub get / analyze / test` **全部不可用**，根因是 flutter_tools 在 `generateCommands` 阶段急切定位 Android SDK，`where.EXE aapt` 子进程创建失败（`CreateFile failed 231`，`process_win.cc:744`）；实测设 `ANDROID_HOME` 指向空目录仍走 `_which('aapt')`（`android_sdk.dart:127`）。

**本次实测的环境变化**：同一台机器上三条命令已可跑通，未做任何仓库配置改动（未设 `ANDROID_HOME`）。原因未取证（工具链/环境差异），**按"当前可用"记录，不作为永久保证**（每次开工前应按 §3 复测）。

---

## 2. 实测结果

| # | 命令 | 结果 | 备注 |
|---|---|---|---|
| 1 | `flutter --version` | ✅ `Flutter 3.47.5 • stable` / `Dart 3.13.4` | — |
| 2 | `flutter pub get` | ✅ `Got dependencies!` | 33 个包有更新但不阻塞 |
| 3 | `flutter analyze` | ✅ `No issues found!` | **修复了一条既有 error 后才零 issue**（见 §3） |
| 4 | `flutter test` | ✅ `+162 -2` | 2 条为**既有红**，非本任务引入（见 §3） |
| 5 | `photo_manager` 最小读相册 demo | ⏸ **未执行** | 需引入依赖 + 真机；本机**未装 Android SDK**（`plt001-probe.md:31` 同结论），APK 构建/安装需在配好 SDK 的机器或先补装 SDK |

---

## 3. 基线订正（本次顺带修复，须单独认领）

| 项 | 修复前 | 修复后 | 说明 |
|---|---|---|---|
| `flutter analyze` | `1 issue found`：`lib/features/memory/presentation/memory_page.dart:192:15` `const_with_non_const`（`ListView` 非 const 构造函数） | **No issues found!** | 该 error 同时让 4 个测试文件加载失败；修法是移除 `const` 并下沉到 `EdgeInsets`/子列表 |
| `flutter test` | `+139 -5`（`router_meta_test` / `memory_page_test` / `widget_test` / `storage_test` / `chat_ledger_page_test`） | **`+162 -2`** | 3 条加载类失败随 §3 第 1 行一并修好 |
| 剩余 2 条既有红 | — | `test/core/storage_test.dart::test_prefs_keys_centralized`（期望 6 / 实际 7）、`test/features/chat_ledger_page_test.dart::renders conversation messages and the real month summary` | **与本任务及 V5.1 无关**，属 HEAD 既有债；未修（不在本任务范围），登记为移动端基线失败集 |

> **基线口径**：后续移动端任务的零回归判据 = **失败集 ⊂ {上述 2 条}**。

---

## 4. 对三期（相册域）的影响

| 门槛 | 状态 | 影响 |
|---|---|---|
| `analyze` / `test` 可跑 | ✅ 已解除 | `APP-034~040` / `APP-043` 的**代码与 gate 验证**不再受阻；`APP-034` 的 D18 守卫（`layer_guards_test.dart`）可真实执行 |
| `pub get` 可跑 | ✅ 已解除 | 三期新增原生依赖的**解析**可行 |
| 真机安装 / 读相册 demo | ⏸ 未验证 | **仍阻塞三期的真机验收**（`plt001-probe.md:31` 的 Android SDK 缺位问题依旧）；需补装 Android SDK 或在已配环境机器上执行 |
| `photo_manager` 版本兼容（`sdk: ^3.13.4`） | ⏸ 未验证 | 引入依赖后须真跑 `pub get` 与最小 demo |

**开工判据（建议）**：`PLT-007` 以「§2 第 1~4 项全绿 + `photo_manager` demo 真机跑通」为闭环；当前**第 5 项未闭环**，故三期仍不建议开工（但已不再是"完全不可验证"状态）。

---

## 5. 复测步骤（每次开工前）

```powershell
cd apps/mobile
flutter --version
flutter pub get
flutter analyze
flutter test
```

判据：`analyze` 零 issue；`test` 失败集 ⊂ §3 的 2 条既有红。

---

## 6. 待办

1. ~~补装 Android SDK 或在已配环境机器上执行 `photo_manager` 最小读相册 demo~~ → **已完成（2026-10-01，见 §7；SDK 实际在位）**。
2. 修复 §3 的 2 条既有红（或明确挂账），把移动端基线恢复到全绿。
3. 本报告结论同步到 `v5.1-task-checklist.md` 的进度台账与 `v5.1-manual-regression-checklist.md` §0。

---

## 7. 依赖面验证补记（2026-10-01）—— 本任务闭环

### 7.1 环境更正

本机 Android SDK **实际在位**：`D:\SDK\Android`（build-tools 35.0.1/36.0.0/37.0.0、emulator、platforms、system-images、platform-tools 齐全），`ANDROID_HOME=D:\SDK\Android` 已设。本文 §1 / §4 与 `plt001-probe.md:31` 的「本机未装 Android SDK」结论**已过时**，以本节为准。

### 7.2 `photo_manager` 解析与构建（仓库外探针工程，仓库零残留）

| # | 项 | 结果 |
|---|---|---|
| 1 | `flutter pub add photo_manager`（Dart 3.13.4 约束） | ✅ 解析成功，无版本冲突 |
| 2 | `flutter build apk --debug` | ✅ 构建成功（构建链：腾讯 gradle wrapper 镜像 + `~/.gradle/init.d/aliyun-mirrors.gradle` + 国内 pub 镜像） |
| 3 | ⚠️ 构建坑登记 | Windows 上 Kotlin btapi 增量编译对 `photo_manager` 报 `Storage … already registered` / `Could not close incremental caches`（清缓存、停 daemon 均复现）；以 `kotlin.incremental=false` 稳定绕过。**三期引入该依赖时须同批写入 `android/gradle.properties`** |

### 7.3 最小读相册 demo（模拟器 `emulator-5554` · Medium_Phone_API_36）

```text
PROBE_RESULT|permission=true|albums=2|assetCount=6|thumb 38 bytes=3133|thumb 39 bytes=3133|thumb 40 bytes=3133
```

| 步骤 | 结果 |
|---|---|
| 授权 | ✅ `requestPermissionExtend → permission=true`（应用 manifest 需自行声明 `READ_MEDIA_IMAGES` / `READ_MEDIA_VIDEO`，`photo_manager` 不自动合并权限） |
| 读数量 | ✅ `albums=2`、`assetCount=6`（`adb shell screencap -p` 灌入 3 张 PNG + `content call --uri content://media --method scan_volume` 触发 MediaStore 索引，数据为真实张数） |
| 读缩略图 | ✅ 3 张 asset 各读出 128×128 缩略图真实字节（`bytes=3133`） |

### 7.4 结论

开工判据（§4）5 项全绿 → **`PLT-007` 闭环，三期（`APP-034~040` / `APP-043`）解除阻塞**。现场清理：探针工程位于仓库外 `C:/tmp/plt007_probe`，仓库无依赖 / 页面残留。
