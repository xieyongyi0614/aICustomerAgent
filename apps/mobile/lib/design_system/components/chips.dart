import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

AppColors _c(BuildContext context) =>
    Theme.of(context).extension<AppColors>()!;
AppTypography _t(BuildContext context) =>
    Theme.of(context).extension<AppTypography>()!;
AppRadii _r(BuildContext context) => Theme.of(context).extension<AppRadii>()!;
AppElevation _e(BuildContext context) =>
    Theme.of(context).extension<AppElevation>()!;
AppGradients _g(BuildContext context) =>
    Theme.of(context).extension<AppGradients>()!;

/// A10 模式 chip
class ModeChip extends StatelessWidget {
  const ModeChip({super.key, required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 11),
      decoration: BoxDecoration(
        color: colors.tagPreferenceBg,
        borderRadius: radii.rFull,
        border: Border.all(color: colors.aiPrimary.withValues(alpha: 0.22)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.auto_awesome, size: 11, color: colors.aiPrimary),
          const SizedBox(width: 5),
          Text(label,
              style: type.label.copyWith(color: colors.aiPrimary, fontSize: 11.5)),
        ],
      ),
    );
  }
}

/// A11 记忆提示条
class MemHint extends StatelessWidget {
  const MemHint({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 13),
      decoration: BoxDecoration(
        color: colors.tagPreferenceBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colors.aiPrimary.withValues(alpha: 0.16)),
      ),
      child: Row(
        children: [
          Icon(Icons.auto_awesome, size: 14, color: colors.aiPrimary),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text,
                style: type.caption
                    .copyWith(color: colors.aiPrimary, fontSize: 12)),
          ),
        ],
      ),
    );
  }
}

/// A12 建议操作 chip
class ChipButton extends StatelessWidget {
  const ChipButton({
    super.key,
    required this.label,
    this.onTap,
    this.ghost = false,
  });

  final String label;
  final VoidCallback? onTap;
  final bool ghost;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 14),
        decoration: BoxDecoration(
          color: ghost ? colors.surface : colors.tagPreferenceBg,
          borderRadius: radii.rFull,
          border: Border.all(
            color: ghost
                ? colors.line
                : colors.aiPrimary.withValues(alpha: 0.20),
          ),
        ),
        child: Text(
          label,
          style: type.label.copyWith(
            color: ghost ? colors.ink2 : colors.aiPrimary,
            fontSize: 12.5,
          ),
        ),
      ),
    );
  }
}

/// A8 输入丸
class AskPill extends StatelessWidget {
  const AskPill({
    super.key,
    this.hint = '问问亚丝娜，或直接说「午饭 35 元」…',
    this.onSend,
  });

  final String hint;
  final VoidCallback? onSend;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    final elevation = _e(context);
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 8, 8, 8),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rFull,
        boxShadow: elevation.card,
      ),
      child: Row(
        children: [
          Icon(Icons.auto_awesome, size: 16, color: colors.aiPrimary),
          const SizedBox(width: 8),
          Expanded(
            child: Text(hint, style: type.body.copyWith(color: colors.ink3)),
          ),
          GestureDetector(
            onTap: onSend,
            child: Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: _g(context).ai,
              ),
              child: Icon(Icons.arrow_upward, size: 17, color: colors.onDeepPrimary),
            ),
          ),
        ],
      ),
    );
  }
}

/// A17 快速捕获条
class CaptureBar extends StatelessWidget {
  const CaptureBar({
    super.key,
    this.hint = '「记一下，下个月准备去旅行」…',
  });

  final String hint;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    final elevation = _e(context);
    return Container(
      margin: const EdgeInsets.only(bottom: 22),
      padding: const EdgeInsets.symmetric(vertical: 13, horizontal: 15),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rMd,
        boxShadow: elevation.card,
      ),
      child: Row(
        children: [
          Icon(Icons.auto_awesome, size: 17, color: colors.aiPrimary),
          const SizedBox(width: 10),
          Expanded(child: Text(hint, style: type.body.copyWith(color: colors.ink3))),
        ],
      ),
    );
  }
}

/// A18 生活模块卡（含 soon 虚线变体）
class ModuleCard extends StatelessWidget {
  const ModuleCard({
    super.key,
    required this.title,
    required this.summary,
    this.icon,
    this.tileBg,
    this.tileFg,
    this.soon = false,
    this.onTap,
  });

  final String title;
  final String summary;
  final IconData? icon;
  final Color? tileBg;
  final Color? tileFg;
  final bool soon;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    final elevation = _e(context);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.fromLTRB(10, 15, 10, 13),
        decoration: soon
            ? BoxDecoration(
                borderRadius: radii.rMd,
                border: Border.all(color: colors.borderDashed, width: 1.5),
              )
            : BoxDecoration(
                color: colors.surface,
                borderRadius: radii.rMd,
                boxShadow: elevation.card,
              ),
        child: Column(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: soon ? colors.fillMuted : (tileBg ?? colors.tileAi),
                borderRadius: BorderRadius.circular(radii.iconTile(42)),
              ),
              child: icon == null
                  ? null
                  : Icon(icon,
                      size: 20,
                      color: soon ? colors.inkOnSoon : (tileFg ?? colors.aiPrimary)),
            ),
            const SizedBox(height: 8),
            Text(
              title,
              style: type.body.copyWith(
                fontWeight: FontWeight.w600,
                color: soon ? colors.ink3 : colors.ink,
              ),
            ),
            Text(
              summary,
              style: type.tabLabel.copyWith(color: colors.ink3),
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    );
  }
}

/// A19 分类支出条
class CategoryBar extends StatelessWidget {
  const CategoryBar({
    super.key,
    required this.label,
    required this.amountLabel,
    required this.ratio,
    required this.gradient,
  });

  final String label;
  final String amountLabel;
  final double ratio;
  final Gradient gradient;

  @override
  Widget build(BuildContext context) {
    final type = _t(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 13),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(label,
                  style: type.body
                      .copyWith(fontWeight: FontWeight.w600, fontSize: 13)),
              const Spacer(),
              Text(amountLabel, style: type.numeric(type.sub)),
            ],
          ),
          const SizedBox(height: 6),
          _BarTrack(ratio: ratio, gradient: gradient),
        ],
      ),
    );
  }
}

class _BarTrack extends StatelessWidget {
  const _BarTrack({required this.ratio, required this.gradient});
  final double ratio;
  final Gradient gradient;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final radii = _r(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        final w = constraints.maxWidth * ratio.clamp(0, 1);
        return Container(
          height: 8,
          decoration: BoxDecoration(
            color: colors.trackBar,
            borderRadius: radii.rFull,
          ),
          child: Align(
            alignment: Alignment.centerLeft,
            child: Container(
              width: w,
              decoration: BoxDecoration(
                gradient: gradient,
                borderRadius: radii.rFull,
              ),
            ),
          ),
        );
      },
    );
  }
}
