import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

/// 按压反馈：按下缩到 [scale]，松开或取消还原（A31 `.97` / A32 pad `.95`）。
///
/// 时长取 `AppMotion.pressScale`（150ms，≤400ms 动效纪律）。
class PressScale extends StatefulWidget {
  const PressScale({
    super.key,
    required this.child,
    this.scale = 0.97,
    this.onTap,
  });

  final Widget child;
  final double scale;
  final VoidCallback? onTap;

  @override
  State<PressScale> createState() => _PressScaleState();
}

class _PressScaleState extends State<PressScale> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final motion = Theme.of(context).extension<AppMotion>()!;
    final interactive = widget.onTap != null;
    return GestureDetector(
      onTap: widget.onTap,
      onTapDown: interactive ? (_) => setState(() => _pressed = true) : null,
      onTapUp: interactive ? (_) => setState(() => _pressed = false) : null,
      onTapCancel: interactive ? () => setState(() => _pressed = false) : null,
      child: AnimatedScale(
        scale: _pressed ? widget.scale : 1,
        duration: motion.pressScale,
        child: widget.child,
      ),
    );
  }
}
