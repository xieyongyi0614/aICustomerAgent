# PLT-007 Flutter 工具链与相册依赖可行性报告

> **任务**：`docs/version/v5.0.0/tasks.md` §15.5 / `docs/version/v5.0.0/tasks/PLT-007.md`（三期硬门槛）
> **结论摘要（2026-09-30）**：**命令行门槛已解除** —— `flutter pub get` / `flutter analyze` / `flutter test` 三条命令在本机真实可用；**原生相册库（`photo_manager`）的可行性仍未验证**（本任务未引入依赖，属三期开工前必做项）。
> **日期**：2026-09-30 ｜ **状态**：**部分完成**（命令面已验证；依赖面无证据）

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

1. 补装 Android SDK 或在已配环境机器上执行 `photo_manager` 最小读相册 demo（授权 → 读数量 → 读缩略图），回填 §2 第 5 行。
2. 修复 §3 的 2 条既有红（或明确挂账），把移动端基线恢复到全绿。
3. 本报告结论同步到 `v5.1-task-checklist.md` 的进度台账与 `v5.1-manual-regression-checklist.md` §0。
