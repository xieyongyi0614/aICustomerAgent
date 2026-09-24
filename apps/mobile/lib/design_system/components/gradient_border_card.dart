import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

/// A2 ai-card：1.5px 渐变描边自绘（不用 ShaderMask）。
class GradientBorderCard extends StatelessWidget {
  const GradientBorderCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.opacity = 0.55,
  });

  final Widget child;
  final EdgeInsets padding;
  final double opacity;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final gradients = Theme.of(context).extension<AppGradients>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    return CustomPaint(
      painter: _GradientBorderPainter(
        gradient: gradients.ai,
        radius: radii.lg,
        opacity: opacity,
      ),
      child: Container(
        padding: padding + const EdgeInsets.all(1.5),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radii.rLg,
          boxShadow: elevation.card,
        ),
        child: child,
      ),
    );
  }
}

class _GradientBorderPainter extends CustomPainter {
  _GradientBorderPainter({
    required this.gradient,
    required this.radius,
    required this.opacity,
  });

  final Gradient gradient;
  final double radius;
  final double opacity;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final rrect = RRect.fromRectAndRadius(rect, Radius.circular(radius));
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5
      ..shader = gradient.createShader(rect);
    paint.color = paint.color.withValues(alpha: opacity);
    canvas.drawRRect(rrect, paint);
  }

  @override
  bool shouldRepaint(covariant _GradientBorderPainter old) =>
      old.opacity != opacity || old.radius != radius;
}
