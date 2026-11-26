# 启动图标与商店素材（手工迁入清单）

> 适用范围：`apps/mobile` 的**桌面图标 + 国内商店提交素材**。落地日期 2026-10-08。
> 与 `icons.md`（Lucide 应用内图标系统）无关：本文只讲品牌图标资产。
> **本工程不预置图标资产**，由开发者按本清单手工迁入；源图 = 仓库根 `logo.png`（1254×1254，带透明通道）。

---

## 0. 先看这条：文件名与清单不可改

- 图标文件名**必须叫 `ic_launcher`**：`AndroidManifest.xml` 已固定引用 `android:icon="@mipmap/ic_launcher"`，改名即失效。
- 五个密度目录必须**齐备**（系统按设备密度取图，不做运行时缩放）；缺档的机型会取邻近密度放大，发虚。
- 全部为 **PNG**，小写文件名。

---

## 路径 A（推荐）：Android Studio 的 Image Asset 一次生成

用 AS 打开 `apps/mobile/android`（或整个工程），`app/src/main/res` 右键 → **New → Image Asset**：

| 步骤 | 设置 |
|---|---|
| Icon Type | `Launcher Icons (Adaptive and Legacy)` |
| Foreground Layer → Source Asset | 选一张**已裁掉透明边、图形居中**的 PNG（1024×1024 或 432×432 均可） |
| Foreground Layer → Resize | 图形占画布 **66%**（对应 108dp 画布的安全区 66dp） |
| Background Layer → Asset Type | `Color` → 填 `F5F4F0`（暖纸白） |
| Options → Legacy | 勾选 `Generate`，同一张图即用于 Android 7 及以下 |
| 生成物 | `mipmap-*/ic_launcher.png`（5 档）+ `mipmap-*/ic_launcher_foreground.png`（5 档）+ `mipmap-anydpi-v26/ic_launcher.xml` + `values/ic_launcher_background.xml` |

> AS 会顺带生成 `ic_launcher_round.png` / `ic_launcher_round.xml`：本工程 Manifest 未引用 `roundIcon`，留着无害、删掉也可。
> AS 生成的背景色落在 `values/ic_launcher_background.xml`；**不要**再另建 `colors.xml` 重复定义同名颜色。

---

## 路径 B：手工裁剪迁入（逐文件清单）

### B1. 必做 · 传统图标（Android 7 及以下）

覆盖现有默认文件（当前为 Flutter 默认图标）：

| # | 路径（`android/app/src/main/res/` 下） | 尺寸 | 内容要求 |
|---|---|---|---|
| 1 | `mipmap-mdpi/ic_launcher.png` | **48×48** | 直角正方形、**不透明底**、图形居中占 70% |
| 2 | `mipmap-hdpi/ic_launcher.png` | **72×72** | 同上 |
| 3 | `mipmap-xhdpi/ic_launcher.png` | **96×96** | 同上 |
| 4 | `mipmap-xxhdpi/ic_launcher.png` | **144×144** | 同上 |
| 5 | `mipmap-xxxhdpi/ic_launcher.png` | **192×192** | 同上 |

- **不要自己切圆角**：圆角/圆形由系统按 ROM 主题处理。
- **不要用透明底**：老系统与部分启动器会把透明区渲染成黑块/白块；建议暖纸白 `#F5F4F0` 或纯白。

### B2. 推荐 · 自适应图标（Android 8+ 实际生效的那套）

> 只做 B1 也能跑，但 Android 8+ 会把传统图标当"老图标"二次加工（缩小 + 外围补白圆），桌面观感明显差一档。

| # | 路径 | 尺寸 | 内容要求 |
|---|---|---|---|
| 6 | `mipmap-mdpi/ic_launcher_foreground.png` | **108×108** | **透明底**，图形只占中间 **66×66** 区域并居中（即图形宽度 = 画布 66%），四周全透明 |
| 7 | `mipmap-hdpi/ic_launcher_foreground.png` | **162×162** | 图形占 66% |
| 8 | `mipmap-xhdpi/ic_launcher_foreground.png` | **216×216** | 图形占 66% |
| 9 | `mipmap-xxhdpi/ic_launcher_foreground.png` | **324×324** | 图形占 66% |
| 10 | `mipmap-xxxhdpi/ic_launcher_foreground.png` | **432×432** | 图形占 66% |

原理：自适应图标画布 108dp，系统只显示中间 **72dp** 并施加遮罩（圆 / 圆角方 / 水滴，各 ROM 不同），**66dp 内才保证任何遮罩与视差动画都不切**。把图形铺满 108dp 会被切掉边角——这正是**必须缩小而不是简单裁剪**的原因。

另需新建两个文件（内容原样复制）：

`android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml`

```xml
<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background" />
    <foreground android:drawable="@mipmap/ic_launcher_foreground" />
</adaptive-icon>
```

`android/app/src/main/res/values/colors.xml`

```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <color name="ic_launcher_background">#F5F4F0</color>
</resources>
```

### B3. 可选 · 主题图标（Android 13+）

系统只读图片的 **alpha 通道**做单色剪影，再用主题色染色：需要再做一套**单色剪影**（图形实心、内部细节用透明挖空，例如把眼睛区域抠掉），尺寸同 B2，文件名：

| # | 路径 | 尺寸 |
|---|---|---|
| 11 | `mipmap-mdpi/ic_launcher_monochrome.png` 等 | 108 / 162 / 216 / 324 / 432 |

并在 `ic_launcher.xml` 里补一行：

```xml
    <monochrome android:drawable="@mipmap/ic_launcher_monochrome" />
```

不做也完全可用（Android 13+ 桌面主题图标对该 App 退化显示常规图标）。

### B4. 商店提交素材（不进 APK，建议建 `apps/mobile/store/`）

| # | 路径 | 尺寸 | 要求 |
|---|---|---|---|
| 12 | `store/icon_512.png` | **512×512** | 直角方形、不透明底；四家通用主图（应用宝 ≤200KB / vivo ≤500KB / OPPO ≤1MB，**压到 200KB 以内最省事**） |
| 13 | `store/icon_216.png` | **216×216** | 部分渠道要求 |
| 14 | `store/icon_1024.png` | **1024×1024** | 备用 / 宣传物料 |

> OPPO 明确要求商店图标**必须与安装包内图标一致**：同底同图，不要一版切圆角、一版不切。

### B5. App 内展示（可选，当前无页面引用）

| # | 路径 | 尺寸 | 说明 |
|---|---|---|---|
| 15 | `assets/brand/logo.png` | 512×512 **透明底** | 放好后需在 `pubspec.yaml` 的 `assets:` 下补一行 `- assets/brand/` 才可被 `Image.asset` 读取 |

---

## 裁剪参数速查（源图 → 各目标）

1. **先裁透明边**：源图四角透明但边缘残留极淡噪点，按"不透明像素边界"裁剪后再用（Pillow：`alpha.point(lambda v: 0 if v < 16 else 255).getbbox()`；PS：图层 → 修剪透明像素）。
2. **再缩放居中**：按目标尺寸建画布，图形宽度 = 画布 × 70%（传统 / 商店）或 × 66%（自适应前景），居中放置。
3. **底**：传统图标与商店图用暖纸白 `#F5F4F0`（与设计系统底色一致，也避免与球体右下蓝紫渐变边界糊在一起）；前景与 App 内资源用透明底。
4. 源图主体最外凸点是**帽檐左上角**：按 66% 缩放到 108dp 画布时，该点在圆形遮罩下会有约 2% 的侵入（落在渐变透明边缘上，肉眼不可见）；要想严格零侵入，把比例降到 **62%**。

---

## 迁入后自检

- 五个 `mipmap-*` 目录各有 `ic_launcher.png`（+ 若做自适应：`ic_launcher_foreground.png`），尺寸与上表逐一对应；
- 打包一次 debug/release 包，桌面图标不等于"白方块/默认 Flutter 图标"；
- Android 8+ 真机：长按图标 → 若 ROM 支持，切换图标形状（圆/方），图形不被切；
- 商店图体积：`icon_512.png` ≤ 200KB（用 TinyPNG 或 `pngquant` 压）。

## 当前状态（2026-10-08）

- 本目录**不含任何图标资产**：`res/mipmap-*` 为 Flutter 模板默认图标，迁入时直接覆盖。
- 商店素材目录 `store/` 尚未创建。
- 本机 Android SDK 缺位（`D:\SDK\Android` 不在盘上、`ANDROID_HOME` 未设），迁入后**无法在本机打包验证**；配好 SDK 后首次构建需确认：图标显示正常、`mipmap-anydpi-v26` 生效、APK 签名来自 `zhaoxi-release.jks`（`keytool -printcert -jarfile <apk>`）。
