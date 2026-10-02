import 'package:flutter/material.dart';

import '../tokens/tokens.dart';
import 'chips.dart';
import 'sparkle.dart';

/// 过程卡步骤（设计系统内独立模型，禁止 import features）。
class ProcStep {
  const ProcStep({
    required this.label,
    required this.status,
    this.detail,
    this.target,
  });

  final String label;
  final String status;
  final String? detail;
  final String? target;
}

/// A14 工具调用过程卡：步骤四态 + 结果落点明示。
/// todo 由服务端一次性下发，客户端零推导总步数。
class ProcCard extends StatelessWidget {
  const ProcCard({
    super.key,
    required this.title,
    required this.steps,
  });

  final String title;
  final List<ProcStep> steps;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    final running = steps.any((s) => s.status == 'running');
    final failed = steps.any((s) => s.status == 'failed');
    final done = !running && !failed && steps.isNotEmpty;

    return Padding(
      padding: const EdgeInsets.only(left: 31, bottom: 14),
      child: Align(
        alignment: Alignment.centerLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 320),
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 15, horizontal: 16),
            decoration: BoxDecoration(
              color: colors.surface,
              borderRadius: radii.rLg,
              boxShadow: elevation.card,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    SparkleIcon(size: 15, color: colors.aiPrimary),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(title,
                          style: type.label.copyWith(
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                            color: colors.ink,
                          )),
                    ),
                    if (running)
                      const _SpinRing()
                    else if (done)
                      Icon(AppIcons.check, size: 13, color: colors.health)
                    else if (failed)
                      Icon(AppIcons.alert, size: 13, color: colors.warm),
                  ],
                ),
                const SizedBox(height: 4),
                for (var i = 0; i < steps.length; i++)
                  _StepRow(
                    step: steps[i],
                    showDivider: i != steps.length - 1,
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({required this.step, required this.showDivider});

  final ProcStep step;
  final bool showDivider;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final isTodo = step.status == 'todo';
    final nameColor = isTodo ? colors.ink3 : colors.ink;
    final detail = step.status == 'done'
        ? (step.target ?? step.detail)
        : step.detail;

    return Container(
      padding: const EdgeInsets.symmetric(vertical: 8),
      decoration: BoxDecoration(
        border: showDivider
            ? Border(
                bottom: BorderSide(
                  color: colors.line,
                  width: 1,
                  style: BorderStyle.solid,
                ),
              )
            : null,
      ),
      child: Row(
        children: [
          SizedBox(width: 20, height: 20, child: _StepIcon(status: step.status)),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              step.label,
              style: type.body.copyWith(
                fontSize: 13.5,
                fontWeight: FontWeight.w600,
                color: nameColor,
              ),
            ),
          ),
          if (detail != null)
            Flexible(
              child: Text(
                detail,
                textAlign: TextAlign.right,
                style: type.numeric(type.caption).copyWith(color: colors.ink3),
              ),
            ),
        ],
      ),
    );
  }
}

class _StepIcon extends StatelessWidget {
  const _StepIcon({required this.status});

  final String status;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    switch (status) {
      case 'done':
        return Container(
          decoration: BoxDecoration(
            color: colors.health.withValues(alpha: 0.14),
            shape: BoxShape.circle,
          ),
          child: Icon(AppIcons.check, size: 12, color: colors.health),
        );
      case 'running':
        return const _SpinRing(size: 20, stroke: 2);
      case 'failed':
        return Container(
          decoration: BoxDecoration(
            color: colors.warm.withValues(alpha: 0.16),
            shape: BoxShape.circle,
          ),
          child: Icon(AppIcons.x, size: 12, color: colors.warm),
        );
      default:
        return Container(
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(color: colors.toggleOff, width: 1.6),
          ),
        );
    }
  }
}

class _SpinRing extends StatefulWidget {
  const _SpinRing({this.size = 15, this.stroke = 1.5});

  final double size;
  final double stroke;

  @override
  State<_SpinRing> createState() => _SpinRingState();
}

class _SpinRingState extends State<_SpinRing>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 900),
  )..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) => CustomPaint(
        size: Size.square(widget.size),
        painter: _RingPainter(
          turns: _c.value,
          track: colors.aiPrimary.withValues(alpha: 0.25),
          head: colors.aiPrimary,
          stroke: widget.stroke,
        ),
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  _RingPainter({
    required this.turns,
    required this.track,
    required this.head,
    required this.stroke,
  });

  final double turns;
  final Color track;
  final Color head;
  final double stroke;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final c = rect.center;
    final r = size.shortestSide / 2 - stroke / 2;
    canvas.drawCircle(
      c,
      r,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke
        ..color = track,
    );
    canvas.drawArc(
      Rect.fromCircle(center: c, radius: r),
      turns * 6.28318,
      1.2,
      false,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke
        ..strokeCap = StrokeCap.round
        ..color = head,
    );
  }

  @override
  bool shouldRepaint(covariant _RingPainter old) => old.turns != turns;
}

/// 结果卡 + 服务端下发 chips（A12）。
class ResultCard extends StatelessWidget {
  const ResultCard({
    super.key,
    required this.summary,
    this.chips = const [],
    this.onChipTap,
  });

  final String summary;
  final List<String> chips;
  final void Function(String chip)? onChipTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    return Padding(
      padding: const EdgeInsets.only(left: 31, bottom: 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(summary,
              style: type.body.copyWith(color: colors.bodyOnBubble)),
          if (chips.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final c in chips)
                    ChipButton(label: c, onTap: () => onChipTap?.call(c)),
                ],
              ),
            ),
        ],
      ),
    );
  }
}
