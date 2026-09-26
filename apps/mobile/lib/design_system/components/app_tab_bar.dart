import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

/// 组件 A9：5 Tab 自绘（禁 M3 系统导航栏）。
/// 中间是悬浮对话球（按钮，无动效），不是 Orb。
class AppTabBar extends StatelessWidget {
  const AppTabBar({
    super.key,
    required this.currentIndex,
    required this.onTap,
  });

  final int currentIndex;
  final ValueChanged<int> onTap;

  static const tabCount = 5;
  static const barHeight = 88.0;
  static const ballSize = 56.0;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    final gradients = Theme.of(context).extension<AppGradients>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final tabs = const [
      _TabSpec(label: '首页', icon: AppIcons.home),
      _TabSpec(label: '生活', icon: AppIcons.layoutGrid),
      _TabSpec(label: '对话', icon: AppIcons.messageCircle),
      _TabSpec(label: '记忆', icon: AppIcons.brain),
      _TabSpec(label: '我的', icon: AppIcons.user),
    ];

    return SizedBox(
      height: barHeight + MediaQuery.of(context).padding.bottom,
      child: DecoratedBox(
        decoration: BoxDecoration(
          color: colors.surface.withValues(alpha: 0.92),
          border: Border(top: BorderSide(color: colors.line)),
        ),
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Row(
              children: [
                for (var i = 0; i < tabCount; i++)
                  if (i == 2)
                    GestureDetector(
                      onTap: () => onTap(2),
                      behavior: HitTestBehavior.opaque,
                      child: SizedBox(
                        width: 76,
                        height: AppTabBar.barHeight,
                        child: Padding(
                          padding: const EdgeInsets.only(top: 36),
                          child: Text(
                            '对话',
                            textAlign: TextAlign.center,
                            style:
                                type.tabLabel.copyWith(color: colors.ink3),
                          ),
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
            Positioned(
              top: -24,
              left: 0,
              right: 0,
              child: Center(
                child: _ChatBall(
                  gradient: gradients.ai,
                  canvas: colors.canvas,
                  shadows: elevation.orbButton(colors.canvas),
                  sparkColor: colors.onDeepPrimary,
                  onTap: () => onTap(2),
                ),
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
        height: AppTabBar.barHeight,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(spec.icon, size: 23, color: color),
            const SizedBox(height: 4),
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
    required this.canvas,
    required this.shadows,
    required this.sparkColor,
    required this.onTap,
  });

  final Gradient gradient;
  final Color canvas;
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
