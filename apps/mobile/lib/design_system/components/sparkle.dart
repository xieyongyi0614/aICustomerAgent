import 'package:flutter/material.dart';

/// ✦ 四芒星（`tokens.md` 固定路径，24 坐标系）。
///
/// 设计系统红线 1 / 7：**AI 相关一律用 ✦，不用 Material 图标**。
/// 尺寸任意，内部按 24 坐标系等比缩放；颜色由调用方经 token 传入。
class SparkleIcon extends StatelessWidget {
  const SparkleIcon({super.key, required this.size, required this.color});

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(painter: SparklePainter(color)),
    );
  }
}

/// ✦ 路径画笔（24 坐标系）。可独立用于 `CustomPaint` 前景 / 背景。
class SparklePainter extends CustomPainter {
  const SparklePainter(this.color);

  static const double _grid = 24;

  static final Path _path = Path()
    ..moveTo(12, 2)
    ..lineTo(14.4, 9.2)
    ..lineTo(22, 12)
    ..lineTo(14.4, 14.8)
    ..lineTo(12, 22)
    ..lineTo(9.6, 14.8)
    ..lineTo(2, 12)
    ..lineTo(9.6, 9.2)
    ..close();

  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    if (size.isEmpty) return;
    canvas.save();
    canvas.scale(size.width / _grid, size.height / _grid);
    canvas.drawPath(_path, Paint()..color = color);
    canvas.restore();
  }

  @override
  bool shouldRepaint(covariant SparklePainter oldDelegate) =>
      oldDelegate.color != color;
}
