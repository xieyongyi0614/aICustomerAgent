import 'package:flutter/material.dart';
import 'package:flutter_hooks/flutter_hooks.dart';

import '../tokens/app_orb_palette.dart';
import 'orb_painter.dart';

export '../tokens/app_orb_palette.dart' show OrbSize, OrbVisualState;

/// AI 核心球：四态 × 三档尺寸。
/// 完成态绽放 600ms 后自动回 idle；可见性靠 TickerMode 停表。
class Orb extends HookWidget {
  const Orb({
    super.key,
    required this.size,
    this.state = OrbVisualState.idle,
    this.paused = false,
  });

  final OrbSize size;
  final OrbVisualState state;

  /// 长列表滚动时由调用方置 true 降频/暂停
  final bool paused;

  static const semanticsLabel = '亚丝娜，AI 助手';

  @override
  Widget build(BuildContext context) {
    final palette = Theme.of(context).extension<AppOrbPalette>()!;
    final effective = useState(state);
    final donePlayed = useState(false);

    useEffect(() {
      if (state != effective.value) {
        if (state == OrbVisualState.done) {
          donePlayed.value = false;
        }
        effective.value = state;
      }
      return null;
    }, [state]);

    final breatheMs = switch (effective.value) {
      OrbVisualState.caring => 1800,
      OrbVisualState.done => 600,
      OrbVisualState.thinking => 4200,
      OrbVisualState.idle => 4200,
    };
    final swirlMs = switch (effective.value) {
      OrbVisualState.thinking => 2400,
      OrbVisualState.idle => 7000,
      OrbVisualState.caring || OrbVisualState.done => 7000,
    };
    final breathPeak = switch (effective.value) {
      OrbVisualState.thinking => 1.08,
      OrbVisualState.done => 1.18,
      _ => 1.055,
    };

    final breathe = useAnimationController(
      duration: Duration(milliseconds: breatheMs),
    );
    final swirl = useAnimationController(
      duration: Duration(milliseconds: swirlMs),
    );

    final ticking = TickerMode.valuesOf(context).enabled;

    useEffect(() {
      if (paused || !ticking) {
        breathe.stop();
        swirl.stop();
        return null;
      }
      if (effective.value == OrbVisualState.done) {
        if (!donePlayed.value) {
          donePlayed.value = true;
          breathe.forward(from: 0).whenComplete(() {
            effective.value = OrbVisualState.idle;
          });
        }
        swirl.stop();
      } else if (effective.value == OrbVisualState.caring) {
        breathe.repeat(reverse: true);
        swirl.stop();
      } else {
        breathe.repeat(reverse: true);
        swirl.repeat();
      }
      return null;
    }, [effective.value, paused, ticking, breatheMs, swirlMs]);

    final breathScale = 1.0 + (breathPeak - 1.0) * breathe.value;
    final swirlTurns = (effective.value == OrbVisualState.caring ||
            effective.value == OrbVisualState.done)
        ? 0.0
        : swirl.value;

    return Semantics(
      label: semanticsLabel,
      child: RepaintBoundary(
        child: SizedBox(
          width: size.px,
          height: size.px,
          child: Transform.scale(
            scale: breathScale,
            child: CustomPaint(
              painter: OrbPainter(
                state: effective.value,
                palette: palette,
                swirlTurns: swirlTurns,
              ),
            ),
          ),
        ),
      ),
    );
  }
}
