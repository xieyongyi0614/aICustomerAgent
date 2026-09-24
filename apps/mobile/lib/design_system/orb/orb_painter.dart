import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../tokens/app_orb_palette.dart';

/// Orb 绘制：只依赖 state，不依赖呼吸进度。
/// 色值一律来自 AppOrbPalette，禁止硬编码色值。
class OrbPainter extends CustomPainter {
  OrbPainter({
    required this.state,
    required this.palette,
    required this.swirlTurns,
  });

  final OrbVisualState state;
  final AppOrbPalette palette;
  final double swirlTurns;

  // 圆心 32% 28% → Alignment(-0.36, -0.44)
  static const _baseCenter = Alignment(-0.36, -0.44);
  static const _stops = [0.0, 0.34, 0.66, 1.0];

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final radius = size.shortestSide / 2;
    final colors = palette.forState(state);

    final base = Paint()
      ..shader = RadialGradient(
        center: _baseCenter,
        radius: 1.0,
        colors: colors,
        stops: _stops,
      ).createShader(rect);

    canvas.saveLayer(rect, Paint());
    canvas.drawCircle(rect.center, radius, base);

    // 内层：screen 叠加 + 旋转（不逐帧重算渐变坐标）
    canvas.save();
    canvas.translate(rect.center.dx, rect.center.dy);
    canvas.rotate(swirlTurns * 2 * math.pi);
    canvas.translate(-rect.center.dx, -rect.center.dy);

    final innerA = Paint()
      ..blendMode = BlendMode.screen
      ..shader = RadialGradient(
        center: const Alignment(0.36, 0.44),
        radius: 0.7,
        colors: [palette.innerCyan, palette.innerCyan.withValues(alpha: 0)],
        stops: const [0.0, 0.46],
      ).createShader(rect);
    canvas.drawCircle(rect.center, radius, innerA);

    final innerB = Paint()
      ..blendMode = BlendMode.screen
      ..shader = RadialGradient(
        center: const Alignment(-0.4, -0.48),
        radius: 0.55,
        colors: [palette.innerWhite, palette.innerWhite.withValues(alpha: 0)],
        stops: const [0.0, 0.30],
      ).createShader(rect);
    canvas.drawCircle(rect.center, radius, innerB);
    canvas.restore();
    canvas.restore();

    // 内描边 1px 白 50%
    canvas.drawCircle(
      rect.center,
      radius - 0.5,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = palette.innerWhite,
    );
  }

  @override
  bool shouldRepaint(covariant OrbPainter oldDelegate) =>
      oldDelegate.state != state ||
      oldDelegate.swirlTurns != swirlTurns ||
      oldDelegate.palette != palette;
}
