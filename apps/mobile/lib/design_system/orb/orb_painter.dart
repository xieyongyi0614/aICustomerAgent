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

    // 外发光：CSS `0 10px 30px rgba(102,90,255,.45)` + `0 0 60px rgba(63,150,255,.35)`，
    // blur-radius ≈ 2σ；先画列表靠后的蓝层，紫层（首列）盖在上面；
    // 必须画在 saveLayer 之外，辉光溢出 76px 方框，进 saveLayer 会被边界裁掉
    canvas.drawCircle(
      rect.center,
      radius,
      Paint()
        ..color = palette.glowSecondary
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 30),
    );
    canvas.drawCircle(
      rect.center + const Offset(0, 10),
      radius,
      Paint()
        ..color = palette.glowPrimary
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 15),
    );

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

    // CSS radial-gradient 默认 farthest-corner，Flutter radius 只认 shortestSide：
    // 青光 CSS 半径 = 46% × 75.2px，白光 = 30% × 77.4px，按 76px 球换算成 0.99 / 1.02
    final innerA = Paint()
      ..blendMode = BlendMode.screen
      ..shader = RadialGradient(
        center: const Alignment(0.36, 0.44),
        radius: 0.99,
        colors: [palette.innerCyan, palette.innerCyan.withValues(alpha: 0)],
        stops: const [0.0, 0.46],
      ).createShader(rect);
    canvas.drawCircle(rect.center, radius, innerA);

    final innerB = Paint()
      ..blendMode = BlendMode.screen
      ..shader = RadialGradient(
        center: const Alignment(-0.4, -0.48),
        radius: 1.02,
        colors: [palette.innerWhite, palette.innerWhite.withValues(alpha: 0)],
        stops: const [0.0, 0.30],
      ).createShader(rect);
    canvas.drawCircle(rect.center, radius, innerB);
    canvas.restore();
    canvas.restore();

    // 内描边 1px 白 50%（innerWhite 本体是高光用的 α0.9，描边按 CSS 降到 0.5）
    canvas.drawCircle(
      rect.center,
      radius - 0.5,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = palette.innerWhite.withValues(alpha: 0.5),
    );
  }

  @override
  bool shouldRepaint(covariant OrbPainter oldDelegate) =>
      oldDelegate.state != state ||
      oldDelegate.swirlTurns != swirlTurns ||
      oldDelegate.palette != palette;
}
