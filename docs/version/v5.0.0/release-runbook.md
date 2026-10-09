# 朝夕 App 免商店分发 · 发布操作手册（PLT-008）

> **上游**：`docs/version/v5.0.0/update-system-architecture.md` §7（发布侧设计）· `docs/version/v5.0.0/tasks/PLT-008.md`（本手册的契约）· `docs/version/v5.0.0/tasks/API-022.md` §4.1.5（入库契约）· `docs/version/v5.0.0/compliance/self-distribution-guide.md` §3.1 / §5（出包步骤与版本签名纪律）。
> **消费方**：`API-022`（按本手册的 manifest 路径与字段入库）、`APP-044`（按 §5 真机清单做端到端验证）、分发执行者。
> **脚本落点**：`apps/backend/scripts/publish_release.py`（发布）与 `apps/backend/scripts/import_release.py`（入库）——两者**成对**放后端 `scripts/`，共用同一套路径安全校验，且可被后端 pytest 直接覆盖。

---

## 0. 前置检查（缺一项就不要出包）

| # | 检查 | 命令 / 判据 | 现状 |
|---|---|---|---|
| 1 | 版本号已递增 | `apps/mobile/pubspec.yaml` 的 `version: x.y.z+n`，`n` 必须**严格大于**上一次发布 | 当前 `0.1.0+1` |
| 2 | 签名配置在位 | `apps/mobile/android/key.properties` + `apps/mobile/android/zhaoxi-release.jks` | **本机存在**（两者均被 `.gitignore` 忽略，绝不入库） |
| 3 | `prod` 注入文件在位 | `apps/mobile/dart_defines/prod.json` | ⬜ **缺失**（`dart_defines/` 下当前只有 `dev.json`）——出 `prod` 包前必须先补，见 `self-distribution-guide.md` §7 缺口登记 |
| 4 | Android SDK build-tools 在 PATH | `aapt2 dump badging <apk>` 与 `apksigner verify --print-certs <apk>` 均可执行 | 发布脚本在缺工具时**硬失败**，不回退 `keytool` |
| 5 | 工作区干净（非强制） | `git status --porcelain` | 不干净只**警告**；manifest 会记录 `commit`，便于回溯`

---

## 1. 出包（构建由 `PLT-005` 负责）

```powershell
cd apps/mobile
flutter clean
flutter pub get
flutter build apk `
  --flavor prod `
  --target-platform android-arm64 `
  --dart-define-from-file=dart_defines/prod.json
```

**三条纪律**（每一条都对应一次真实事故，见 `self-distribution-guide.md:101-102`）：

1. **必须带 `--flavor prod`**：不带 flavor 时后端地址等注入不生效，包装到别人手机上直接不可用。
2. **必须显式 `--target-platform android-arm64`**：默认产物可能只含模拟器 ABI（x86_64）引擎，真机一启动就白屏闪退。
3. **`--dart-define-from-file` 指向 `dart_defines/prod.json`**：该文件当前缺失（见 §0 第 3 项），未补齐前**不要**对外分发 `prod` 包。

产物落在 `apps/mobile/build/app/outputs/flutter-apk/app-prod-release.apk`（flavor 后缀由 Gradle 决定，以实际文件名为准）。

---

## 2. 发布：制品归档 + 校验信息 + manifest

```powershell
cd apps/backend
uv run python -m scripts.publish_release `
  --apk ../mobile/build/app/outputs/flutter-apk/app-prod-release.apk `
  --channel prod `
  --storage-dir ./releases `
  --min-supported-version-code 1 `
  --release-notes-file ./notes/0.2.0.md
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--apk` | 是 | 已签名 APK 路径 |
| `--channel` | 是 | `prod` / `dev`；与产物的 `applicationId` **必须匹配**（`prod`↔`com.zhaoxi.app`、`dev`↔`com.zhaoxi.app.dev`），否则拒绝 |
| `--storage-dir` | 是 | 制品根目录；容器内为 `/srv/backend/releases`，本地开发建议放仓库外或 `.tmp/` |
| `--min-supported-version-code` | 否（默认 `0`） | 低于此 `versionCode` 的客户端将被判为强制更新 |
| `--force-update` | 否 | 显式强制位（服务端原样下发） |
| `--release-notes` / `--release-notes-file` | 否 | 更新说明**纯文本**；后者优先。长度上限 = `APP_RELEASE_NOTES_MAX_CHARS`（默认 2000） |
| `--expect-version-code` | 否 | 与产物反读值双重确认（CI 建议传） |
| `--allow-republish` | 否 | 同号重发才加；默认要求 `versionCode` 单调递增 |

**脚本会做什么**（顺序固定）：

1. 校验 `key.properties` 存在（缺失即拒绝——release 会**静默回退 debug 签名**）；
2. `aapt2 dump badging` **反读** `versionCode` / `versionName` / `package`（**不解析 `pubspec.yaml`**）；
3. `apksigner verify --print-certs` 读签名 —— 门禁：DN 含 `Android Debug` 或命中已知 debug 摘要 → **拒绝**；
4. 校验 flavor 与 `--channel` 匹配、APK 内含 `lib/arm64-v8a/libflutter.so`、`versionCode` 单调递增；
5. 归档到 `{storage}/{channel}/{version_code}/full/zhaoxi-<versionName>+<versionCode>-<channel>.apk`；
6. 产出**同目录**的 `release-manifest.json`。

**它不会做什么**：不重签名、不二次压缩、不修改 APK、不写数据库（入库是下一步）。

---

## 3. 核对 manifest（人工过一眼）

```powershell
Get-Content ./releases/prod/<versionCode>/full/release-manifest.json
```

| 字段 | 期望 |
|---|---|
| `schema_version` | `1`（未知版本入库会被拒绝，fail-closed） |
| `platform` / `channel` | `android` / `prod` |
| `version_code` / `version_name` | 与 `aapt2 dump badging` 输出**逐字符一致** |
| `min_supported_version_code` | `<= version_code` |
| `published_at` / `built_at` | ISO-8601（UTC，带 `+00:00`） |
| `commit` | 出包提交号（`unknown` 表示不在 git 工作区） |
| `artifact.type` | `full`（差分未实现） |
| `artifact.size_bytes` / `sha256` | 与 `Get-FileHash -Algorithm SHA256` 输出一致（sha256 小写、无分隔） |
| `artifact.signature_fingerprint` | **大写、冒号分隔**的 SHA-256 指纹（`apksigner` 原始输出为连续小写十六进制，脚本已归一化） |
| `artifact.from_version_code` | `full` 恒 `null`（`patch` 专用） |

---

## 4. 入库

```powershell
uv run python -m scripts.import_release --manifest ./releases/prod/<versionCode>/full/release-manifest.json --storage-dir ./releases
```

**入库会做的事**：① 校验 `schema_version == 1`；② 枚举域校验（platform / channel / type / 版本号区间 / 说明长度）；③ 路径解析后必须仍在 `--storage-dir` 之下；④ **重算** `size_bytes` 与 `sha256` 并与 manifest 比对；⑤ 以 `(platform, channel, version_code)` 幂等 upsert。

**幂等**：同 manifest 连跑两次不会产生第二行（第二次打印「更新」而非「新增」）。任一校验不过 → 非 0 退出且**不部分写入**。

**为什么没有「后台上传页」**：内测期无可信管理鉴权体系（`IDENT-010` 调试面鉴权仍留白），开放未鉴权写接口 = 任何人可推假版本；本脚本的攻击面 = 服务器本地文件权限。

**容器部署**：`docker-compose.yml` 已挂载命名卷 `asuna_releases:/srv/backend/releases`，并注入 `APP_RELEASE_STORAGE_DIR=/srv/backend/releases`（两处必须同值）。容器内入库：

```powershell
docker compose exec console uv run python -m scripts.import_release --manifest /srv/backend/releases/prod/<versionCode>/full/release-manifest.json
```

---

## 5. 真机验证清单（`APP-044` 端到端）

| # | 步骤 | 期望 |
|---|---|---|
| 1 | 旧版本机型（`version_code` 小于新版本）打开 App | 首帧后自动检查命中，弹出更新面板 |
| 2 | 点「立即更新」 | 下载进度可见；弱网中断后点重试，服务端日志出现 `206` |
| 3 | 下载完成 | 校验通过并跳转系统安装器（首次需在系统设置里允许「安装未知应用」） |
| 4 | 完成安装并冷启动 | 我的页 / 关于页版本号变为新版本 |
| 5 | 服务端把制品替换为**篡改包** | 校验失败，**不进入安装**，临时文件被删 |
| 6 | 服务端把制品替换为**异签名包** | 指纹比对被拦，提示「需卸载重装」 |
| 7 | `dev` flavor 包 | 只检测提示，**不下载不安装**（按钮为「前往发布页下载」） |
| 8 | 低于 `min_supported_version_code` 的机型 | 强制更新面板，无任何关闭路径 |

---

## 6. 回滚与重发

| 场景 | 做法 |
|---|---|
| 已发布版本有问题，需要撤回提示 | 直接删库行（`app_releases` + 其 `app_release_artifacts`）：查询取 `version_code` 最大值，删除后自动回退到上一个版本 |
| 同号重发包（修包不升号） | 发布脚本加 `--allow-republish`；入库走同一幂等路径（覆盖 `sha256` / `size_bytes`） |
| 客户端已下载坏包 | `sha256` 校验会拦住，无需服务端干预 |

---

## 7. 差分（补丁）扩展位——**本期不实现**

契约已就位，接差分时**只加 `type` 取值，不改结构**：

| 项 | 未来形态 |
|---|---|
| 制品命名 | `zhaoxi-<versionName>+<versionCode>-<flavor>-patch-from-<fromVersionCode>.patch` |
| 归档布局 | `{storage}/{channel}/{version_code}/patch/` |
| manifest | **第二份** `release-manifest.json`：其余字段同 §3，`artifact.type = "patch"`、`artifact.from_version_code = <基线 versionCode>` |
| 数据面 | `app_release_artifacts.artifact_type` 的 CHECK **已预置 `'patch'`**，无需改迁移 |
| 校验口径 | 补丁文件自身有 `sha256`；**合成后**的新 APK 走与全量**完全相同**的双校验链 |

客户端在本期遇到未知 `type` 一律 **fail-closed 忽略**（不猜测、不降级），因此本期下发 `patch` 制品不会造成任何副作用——但**也没有收益**，故本期不下发。
