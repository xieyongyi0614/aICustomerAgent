import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

/// 组件 A9：4 Tab 自绘（禁 M3 系统导航栏）。
/// 第 3 位是悬浮对话球（按钮，无动效），不是 Orb。
/// 「记忆」不是主 Tab（红线 10 / 2026-09-30 IA 裁决）：它从「我的 · 记忆管理」与生活宫格进入。
class AppTabBar extends StatelessWidget {
  const AppTabBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
  });

  final int currentIndex;
  final ValueChanged<int> onTap;

  /// A9：4 个位置 —— 首页 / 生活 / 对话（悬浮球）/ 我的。
  static const tabCount = 4;
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

  /// 设计稿 `.orb-tab span{margin-top:36px}`：同样相对 `.orb-tab` 项算，
  /// 故对话文字相对栏顶 = 12 + 36 = 48。
  static const orbLabelTop = 48.0;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    final gradients = Theme.of(context).extension<AppGradients>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final tabs = const [
      _TabSpec(label: '首页', icon: AppIcons.home),
      _TabSpec(label: '生活', icon: AppIcons.layoutGrid),
      // 第 3 位由悬浮球承载，图标仅占位保持索引对齐
      _TabSpec(label: '对话', icon: AppIcons.messageCircle),
      _TabSpec(label: '我的', icon: AppIcons.user),
    ];

    final inset = MediaQuery.of(context).padding.bottom;
    // 设计稿栏高 88（原型把 home indicator 画在 88 内）：安全区落在文字下方的空白里，
    // 故 88 是「含安全区」的目标高度，只在安全区更高时才追加高度。
    final height = math.max(barHeight, inset + contentTop + contentHeight);
    return SizedBox(
      height: height,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: colors.surface.withValues(alpha: 0.92),
          border: Border(top: BorderSide(color: colors.line)),
        ),
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Padding(
              padding: const EdgeInsets.only(
                top: contentTop,
                left: sidePadding,
                right: sidePadding,
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (var i = 0; i < tabCount; i++)
                    if (i == 2)
                      // 对话位：文字与悬浮球都定位在本项内（`.orb-tab{position:relative}`），
                      // 球因此落在 4 位里的第 3 位（62.5%）而不是整栏居中。
                      GestureDetector(
                        onTap: () => onTap(2),
                        behavior: HitTestBehavior.opaque,
                        child: SizedBox(
                          width: orbSlotWidth,
                          height: contentHeight,
                          child: Stack(
                            clipBehavior: Clip.none,
                            children: [
                              Positioned(
                                top: orbLabelTop - contentTop,
                                left: 0,
                                right: 0,
                                child: Text(
                                  '对话',
                                  textAlign: TextAlign.center,
                                  style: type.tabLabel
                                      .copyWith(color: colors.ink3),
                                ),
                              ),
                              Positioned(
                                top: ballTop - contentTop,
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
                        ),
                      )
                    else
                      Expanded(
                        child: _TabItem(
                          spec: tabs[i],
                          selected: currentIndex == i,
                          onTap: () => onTap(i),
                        ),
                      ),
                ],
              ),
            ),
          ],
        ),
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
      child: Container(
        width: AppTabBar.ballSize,
        height: AppTabBar.ballSize,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: gradient,
          boxShadow: shadows,
        ),
        child: CustomPaint(painter: _SparklePainter(sparkColor)),
      ),
    );
  }
}

/// ✦ 四芒星（tokens.md 固定路径，24 坐标系）
class _SparklePainter extends CustomPainter {
  const _SparklePainter(this.color);

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..moveTo(12, 2)
      ..lineTo(14.4, 9.2)
      ..lineTo(22, 12)
      ..lineTo(14.4, 14.8)
      ..lineTo(12, 22)
      ..lineTo(9.6, 14.8)
      ..lineTo(2, 12)
      ..lineTo(9.6, 9.2)
      ..close();
    canvas.translate(size.width / 2 - 12, size.height / 2 - 12);
    canvas.drawPath(path, Paint()..color = color);
  }

  @override
  bool shouldRepaint(covariant _SparklePainter oldDelegate) =>
      oldDelegate.color != color;
}
