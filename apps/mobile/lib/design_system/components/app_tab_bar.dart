import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../tokens/tokens.dart';
import 'sparkle.dart';

/// 组件 A9：5 Tab 自绘（禁 M3 系统导航栏）。
/// 第 3 位是悬浮对话球（按钮，无动效），不是 Orb；第 2 位是可变的「动态」槽。
/// 「记忆」不是主 Tab（红线 10 / 2026-09-30 / 2026-10-03 IA 裁决）：它从「我的 · 记忆管理」与生活宫格进入。
class AppTabBar extends StatelessWidget {
  const AppTabBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
    this.dynamicLabel = '记账',
    this.dynamicIcon = AppIcons.wallet,
  });

  final int currentIndex;
  final ValueChanged<int> onTap;

  /// 动态槽的文案与图标：由壳层按用户设定注入（默认「记账」）。
  final String dynamicLabel;
  final IconData dynamicIcon;

  /// A9：5 个位置 —— 首页 / 动态 / 对话（悬浮球）/ 生活 / 我的。
  static const tabCount = 5;
  static const barHeight = 88.0;
  static const ballSize = 56.0;

  /// 设计稿 A9 `.tabbar{padding:12px 10px 0; align-items:flex-start}`：
  /// 内容顶部对齐、上内边距 12、左右内边距 10。
  static const contentTop = 12.0;
  static const sidePadding = 10.0;

  /// 图标 23 + 间隙 3 + 文字行高 ≈ 18（同时作为 Tab 的可点高度）。
  static const contentHeight = 44.0;
  static const iconSize = 23.0;
  static const labelGap = 3.0;
  static const orbSlotWidth = 76.0;

  /// 悬浮球相对栏顶的位置：`.orb-btn{top:-24px}` 是相对 `.orb-tab` 项算的，
  /// 而 `.orb-tab` 已落在栏顶内边距 12 之下 → 相对栏顶 = 12 - 24 = -12。
  static const ballTop = -12.0;

  /// 悬浮球溢出栏顶的高度。本组件把自己的盒子向上多留这么多（视觉栏体仍只占下方 88），
  /// 否则球顶那 12px 落在组件边界外，按 `RenderBox.hitTest` 先判 `size.contains` 的规矩，
  /// 绘制得出来却永远点不到。
  static const ballOverflow = -ballTop;

  /// 设计稿 `.orb-tab span{margin-top:36px}`：同样相对 `.orb-tab` 项算，
  /// 故对话文字相对栏顶 = 12 + 36 = 48。
  static const orbLabelTop = 48.0;

  /// 对话位（文字位）命中盒：自栏顶量到「对话」文字下沿（10.5px 文字的行盒按 16 计）。
  /// 悬浮球不在此盒内——它独立挂在最外层 Stack 上，见 `build`。
  static const orbHitHeight = orbLabelTop + 16.0;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    final gradients = Theme.of(context).extension<AppGradients>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final tabs = [
      const _TabSpec(label: '首页', icon: AppIcons.home),
      _TabSpec(label: dynamicLabel, icon: dynamicIcon),
      // 第 3 位由悬浮球承载，图标仅占位保持索引对齐
      const _TabSpec(label: '对话', icon: AppIcons.messageCircle),
      const _TabSpec(label: '生活', icon: AppIcons.layoutGrid),
      const _TabSpec(label: '我的', icon: AppIcons.user),
    ];

    final inset = MediaQuery.of(context).padding.bottom;
    // 设计稿栏高 88（原型把 home indicator 画在 88 内）：安全区落在文字下方的空白里，
    // 故 88 是「含安全区」的目标高度，只在安全区更高时才追加高度。
    final visualHeight = math.max(barHeight, inset + contentTop + contentHeight);
    // 盒子比视觉栏体高 ballOverflow：多出来的那一条是透明的，专门容纳溢出的球顶。
    return SizedBox(
      height: visualHeight + ballOverflow,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned(
            top: ballOverflow,
            left: 0,
            right: 0,
            bottom: 0,
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: colors.surface.withValues(alpha: 0.92),
                border: Border(top: BorderSide(color: colors.line)),
              ),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: sidePadding),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (var i = 0; i < tabCount; i++)
                      if (i == 2)
                        // 对话位：只承载「对话」文字，球独立挂在最外层（见下）。
                        // 本项自栏顶起算（其余位改在项内补 12 内边距），文字下沿才落在命中盒内。
                        GestureDetector(
                          onTap: () => onTap(2),
                          behavior: HitTestBehavior.opaque,
                          child: SizedBox(
                            width: orbSlotWidth,
                            height: orbHitHeight,
                            child: Stack(
                              clipBehavior: Clip.none,
                              children: [
                                Positioned(
                                  top: orbLabelTop,
                                  left: 0,
                                  right: 0,
                                  child: Text(
                                    '对话',
                                    textAlign: TextAlign.center,
                                    style: type.tabLabel
                                        .copyWith(color: colors.ink3),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        )
                      else
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.only(top: contentTop),
                            child: _TabItem(
                              spec: tabs[i],
                              selected: currentIndex == i,
                              onTap: () => onTap(i),
                            ),
                          ),
                        ),
                  ],
                ),
              ),
            ),
          ),
          // 悬浮球独立挂在最外层 Stack：父盒覆盖整球（含溢出栏顶的那 12px）→ 整球可点。
          // 左右各 2 位等分 + 中间固定 76 → 本组件水平中线即中间位中线，Center 即可对齐。
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: Center(
              child: _ChatBall(
                gradient: gradients.ai,
                shadows: elevation.orbButton(colors.canvas),
                sparkColor: colors.onDeepPrimary,
                onTap: () => onTap(2),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TabSpec {
  const _TabSpec({required this.label, required this.icon});
  final String label;
  final IconData icon;
}

class _TabItem extends StatelessWidget {
  const _TabItem({
    required this.spec,
    required this.selected,
    required this.onTap,
  });

  final _TabSpec spec;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final color = selected ? colors.ink : colors.ink3;
    return InkWell(
      onTap: onTap,
      child: SizedBox(
        height: AppTabBar.contentHeight,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(spec.icon, size: AppTabBar.iconSize, color: color),
            const SizedBox(height: AppTabBar.labelGap),
            Text(spec.label, style: type.tabLabel.copyWith(color: color)),
          ],
        ),
      ),
    );
  }
}

/// 悬浮对话球：ai 线性渐变 + 白✦，无呼吸动效（是按钮，不是生命体）。
class _ChatBall extends StatelessWidget {
  const _ChatBall({
    required this.gradient,
    required this.shadows,
    required this.sparkColor,
    required this.onTap,
  });

  final Gradient gradient;
  final List<BoxShadow> shadows;
  final Color sparkColor;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      // 球体自身必须 opaque：BoxDecoration 的 DecoratedBox 与 CustomPaint 的 SparklePainter
      // 都不参与命中测试，默认 deferToChild 会让这个手势识别器永远收不到点击。
      behavior: HitTestBehavior.opaque,
      child: Container(
        width: AppTabBar.ballSize,
        height: AppTabBar.ballSize,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: gradient,
          boxShadow: shadows,
        ),
        child: Center(child: SparkleIcon(size: 24, color: sparkColor)),
      ),
    );
  }
}
