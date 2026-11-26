# PLT-001 手环数据探针使用指引

> 目的：在真机上验证「Mi Fitness 国内版是否原生写入 Health Connect（健康互联）」（P1）、可读字段（P2）与同步延迟（P3），产出可粘贴进 `docs/version/v5.0.0/phase0-miband-validation.md` 的证据草稿。
> 结论未出前，M4 健康段（API-009~010 / APP-023~025）保持门控（`docs/version/v5.0.0/tasks.md:194`）。

## 探针组成

| 文件 | 说明 |
|---|---|
| `lib/features/health/data/health_connect_probe.dart` | 采集逻辑：18 个类型的授权检查、近 N 天读取、来源包名归集、延迟分档、报告草稿生成 |
| `lib/features/health/presentation/health_probe_page.dart` | 探针页（健康页 → 「PLT-001 手环数据探针」进入，路由 `/health/probe`） |
| `test/features/health/health_connect_probe_test.dart` | 14 个单测（mock `Health`，验证聚合 / P1 判定 / 延迟分档 / 报告文本） |
| `android/app/src/main/AndroidManifest.xml` | 新增 15 个 `android.permission.health.READ_*` + `ACTIVITY_RECOGNITION` + queries + `ViewPermissionUsageActivity` alias |
| `MainActivity.kt` | `FlutterActivity` → `FlutterFragmentActivity`（Android 14+ Health Connect 授权流程要求） |

## 前置条件

1. 真机：Android 13+（Android 14+ 内置健康互联；13 需从应用商店装 Health Connect）。
2. 手机已装 **Mi Fitness（小米运动健康）国内版** 并与小米手环 9 Pro 配对；手环日常佩戴有数据（步数 / 心率 / 睡眠至少一类）。
3. 测量期间**不要**连接 Gadgetbridge 等第三方 App（与官方 App 互斥，REPORT.md §6）。

## 操作步骤

### 第一步：装探针 App

```bash
cd apps/mobile
flutter run --flavor dev -d <设备ID>      # 或 flutter build apk --debug --flavor dev 后 adb install
```

> 本机（仓库所在机）未装 Android SDK；APK 构建需在已配好 `ANDROID_HOME` 的机器执行。

### 第二步：P1 原生写入判定

1. 手机系统设置 → 搜索「健康互联 / Health Connect」→ 打开。
2. 进入「数据来源 / 已连接的应用」，**截图**：看列表里是否出现「小米运动健康 / Mi Fitness」。
   - 出现 → P1 初判成立（原生写入）；不出现 → 记录 Mi Fitness 内是否存在「同步到健康平台 / 健康互联」开关（区分「不支持」与「需手动开启」，PLT-001 §4.1.2 第 5 步）。
3. 打开朝夕 App → 健康 Tab → 点「PLT-001 手环数据探针（验证工具）」。
4. 探针页会先显示 Health Connect 可用性；点「申请权限并读取近 7 天」，系统弹出健康互联授权页 → 全部允许。
5. 看 **P1 · 原生写入** 卡片：来源 chips 里出现 `Mi Fitness（com.xiaomi.wearable）` 即探针侧证据成立。**截图**。

### 第三步：P2 字段清单

读完后逐行核对「P2 · 可读字段」卡片：每行显示授权状态、条数、最新值 + 单位 + 最新时刻 + 来源。对每个**有数据**的字段，到 Mi Fitness / 健康互联里核对同一时刻数值是否一致（抽查 2~3 个即可），记录采样频率（smart / 1min / 10min / 30min，见手环心率设置等）。调研基线 12 类中探针未覆盖的 `VO2 Max`（health 包未暴露该类型）直接标「实测缺失（插件不支持）」。

### 第四步：P3 延迟测量（≥ 3 次、覆盖两类数据）

1. 在手环上产生一条可辨认的数据：如原地走 30 步（步数）、摘戴手环测一次心率（心率）。
2. 记下 Mi Fitness 里该数据可见的时刻（=「数据产生时刻」近似，两者都算作 Mi Fitness 可见口径）。
3. 探针页 P3 卡片选类目 → 点「延迟采样」：显示该类最新记录的结束时刻、数据龄与分档（实时 ≤5min / 近实时 ≤1h / 延迟 >1h）。
4. 重复 3 次（至少两类数据），把「数据产生时刻 - 记录结束时刻」人工补记进报告。
5. 若始终采不到 → 点「复制报告草稿」前如实记录（可能是「仅手动触发」档：打开 Mi Fitness 同步后才能读到）。

### 第五步：出报告草稿

点「复制报告草稿」→ 粘贴到 `docs/version/v5.0.0/phase0-miband-validation.md`，补齐【待填】环境字段（手环固件、手机型号、Android 版本、Mi Fitness 版本与区域版本、Health Connect 版本）与 P3 的数据产生时刻，按 PLT-001 §4.1.5 十段结构成稿，三档结论（通过 / 未通过 / 部分通过）+ 排期建议。证据截图放 `docs/version/v5.0.0/phase0-evidence/`（命名含日期与 P1/P2/P3）。

## 自动化测试（PC 上跑，不依赖真机）

```bash
cd apps/mobile
flutter test test/features/health/health_connect_probe_test.dart   # 14 用例
```

单测覆盖：采集类型全部在 Health Connect 支持清单内、调研基线覆盖度、权限常量与 Manifest 一致、按类型聚合（条数 / 最新点 / 来源）、未授权不读取、单类型异常隔离、Health Connect 不可用降级、P1 判定两个分支、延迟分档边界、报告文本结构。**它们验证的是探针逻辑本身**；「能否拿到手环数据」必须真机执行（平台通道 + 真实 Health Connect，mock 不了）。

## 已知边界

- HRV 只有 RMSSD 口径（Health Connect 不收 SDNN）；VO2 Max、血压、压力不在 Health Connect 标准读类型内（REPORT.md §2.4）。
- Health Connect 默认只回溯**授权时刻起 30 天**的历史；探针读 7 天窗口不受影响。
- 探针页是验证工具，PLT-001 出结论后按裁决去留（APP-023 落地时由正式链路替换）。
