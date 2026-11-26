# 图标系统（Lucide · 本地 TTF）

> 适用范围：`apps/mobile` 全部 UI。裁决日期 2026-09-26；与设计系统红线（`图标用 Lucide 不用 Material Icons`）配套。

## 一句话结论

**本地 TTF + 生成器 + 守卫测试**：码点永远由 `fonts/lucide.ttf` 的 cmap 决定，人只读写语义名（`AppIcons.brain`），从不开手抄十六进制。不使用任何图标 npm/pub 包。

## 为什么不用图标包（裁决记录）

| 方案 | 结论 | 依据 |
|---|---|---|
| `lucide_icons` 0.257.0 | **否决（已死依赖）** | Flutter 3.47 起 `IconData` 是 final class，该包 `class LucideIconData extends IconData` 直接编译不过（实测报错）；包自 2023 年停更。lib/ 零引用，pubspec 里的声明待移除 |
| `lucide_icons_flutter` 3.1.20 | **审查后否决（2026-09-26）** | 可信度没问题（认证发布者 / MIT / 持续更新 / 纯 const IconData 兼容 3.47 / SDK `^3.0.0`），但：捆 7 个 TTF 共 32MB 字体资产（基础 + 5 档字重 + RTL 变体，release tree-shaking 后留多少需实测）；单文件 29,372 个 IconData 常量（源码十几 MB，拖慢构建与 IDE）；单维护者、非 lucide 官方；包升级 = 字体版本漂移 = golden 基线全动 |
| **本地 TTF + 生成器（现状）** | **采用** | 单文件 413KB 钉死、零外部依赖、视觉零漂移；可读性与防漂移由生成器 + 守卫测试解决 |

**何时重新考虑包方案**：图标需求频繁扩张、需要持续跟进上游新图形时。迁移路径已探明：`AppIcons` 各常量改为转发 `LucideIcons.xxx`（调用点零改动）→ 删本地 ttf 与生成器 → 实测 release APK 体积 → golden 重新生成。

## 架构与数据流

```text
fonts/lucide.ttf                      全量 Lucide 字体（413KB；cmap 1192 码点，format 4；
  │ pubspec 声明 family = lucide       字形命名属旧版 lucide 风格：alert-circle / home）
  ▼
tool/gen_app_icons.py                 生成器：ICONS 表登记 (dart 名, lucide 字形名)，
  │ 读取 cmap 反查码点                  缺字形 / 码点冲突直接报错
  ▼ 生成
lib/design_system/tokens/app_icons.dart    GENERATED 文件，勿手改；
  │ 语义常量 AppIcons.xxx                   非直觉映射带 // lucide: 原名 注释
  ▼ 调用
Icon(AppIcons.brain)                  业务代码只出现语义名，禁止裸 IconData
  ▲ 守卫
test/design_system/app_icons_font_test.dart  纯 Dart 解析 cmap format 4（不依赖 python 进 CI），
                                             断言声明的每个码点在字体中真实存在且无重复
```

## 日常操作

### 加一个图标

1. 在 [lucide.dev](https://lucide.dev/icons) 找到图标的 kebab-case 字形名（如 `arrow-left-right`）。
2. 在 `tool/gen_app_icons.py` 的 `ICONS` 表登记一行：`("dartName", "lucide-glyph-name"),`。
3. 重跑 `python tool/gen_app_icons.py`（本机需 fonttools），然后代码里直接 `Icon(AppIcons.dartName)`。

脚本会做三道校验：字形不存在 → 报错；码点与已有图标冲突 → 报错；dart 名与字形名不一致时自动补 `// lucide: 原名` 注释。

### 升级字体文件

1. 替换 `fonts/lucide.ttf`（新版 lucide 的 ttf）。
2. 重跑 `python tool/gen_app_icons.py`——**码点可能整体变化，以新 cmap 为准**；注意新版 lucide 改过字形名（如 `alert-circle` → `circle-alert`、`home` → `house`），ICONS 表里的字形名要对应改。
3. `flutter test`：守卫测试若红，说明 ICONS 表里有字形在新字体中不存在；golden 若红属预期（字形轮廓微调），`flutter test --update-goldens` 重新生成并人工过目。

### 禁止事项

- **禁止手抄/手改 `app_icons.dart` 的码点**——它是生成文件，下次生成会被覆盖；手抄脱节正是 2026-09-26 豆腐块事故（17 个码点与字体不符，整页图标渲染为方块）的根因。
- 禁止在业务代码里写 `IconData(0x…)` 或 `Icons.*`（Material）。

## 使用规范（与设计系统红线衔接）

- 调用只写语义名：`Icon(AppIcons.brain, size: 16, color: colors.aiPrimary)`。
- 常用映射对照：`checklist` → list-checks、`swap` → arrow-left-right、`alert` → alert-circle（文件内均有注释）。
- **Material 图标清退中**：`proc_card.dart` / `chips.dart` 等仍有 10+ 处 `Icons.*`（auto_awesome / check_circle 等）。因此 pubspec 的 `uses-material-design: true` **暂时不能删**（删了这些位置全部变豆腐块）；全部替换完成后删除该行，可为 APK 省约 1.5MB——独立收尾项，不在本文件范围内。

## 验证

```bash
flutter test test/design_system/app_icons_font_test.dart   # 码点 × 字体 cmap 校验
python tool/gen_app_icons.py                               # 确认生成物与库内一致（无 diff 即无手改）
flutter test                                               # 全量（含 golden 视觉回归）
```
