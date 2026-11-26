import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

/// A34 loan-card（车贷进度卡）：深色卡 + warm 进度条。
///
/// 进度填充锁定 `gradients.warmBar`，**不接受外部色**——进度不是 AI 语义，
/// 暴露色参等于把误用 ai 渐变的可能交给调用方（skill `components.md:338` 明文禁令）。
class LoanCard extends StatelessWidget {
  const LoanCard({
    super.key,
    required this.label,
    required this.remainingText,
    required this.progress,
    this.badgeText,
    this.subText,
    this.leftNote,
    this.rightNote,
  });

  static const progressFillKey = ValueKey('loan-card-progress-fill');

  final String label;
  final String remainingText;
  final double progress;
  final String? badgeText;
  final String? subText;
  final String? leftNote;
  final String? rightNote;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final spacing = Theme.of(context).extension<AppSpacing>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    final gradients = Theme.of(context).extension<AppGradients>()!;
    final ratio = progress.isNaN ? 0.0 : progress.clamp(0.0, 1.0);
    return Container(
      padding: EdgeInsets.all(spacing.cardPadding),
      decoration: BoxDecoration(
        gradient: gradients.deepSummary,
        borderRadius: radii.rLg,
        boxShadow: elevation.deep,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: type.caption.copyWith(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: colors.onDeepSecondary,
                  ),
                ),
              ),
              if (badgeText != null)
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: colors.warm.withValues(alpha: 0.22),
                    borderRadius: radii.rFull,
                  ),
                  child: Text(
                    badgeText!,
                    style: type.caption.copyWith(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: Color.lerp(
                        colors.warm,
                        colors.onDeepPrimary,
                        0.35,
                      ),
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 11),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Flexible(
                child: Text(
                  remainingText,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: type.amountHero.copyWith(
                    fontSize: 30,
                    letterSpacing: -0.6,
                    color: colors.onDeepPrimary,
                  ),
                ),
              ),
              if (subText != null) ...[
                const SizedBox(width: 7),
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    subText!,
                    maxLines: 1,
                    style: type.caption.copyWith(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: colors.onDeepSecondary,
                    ),
                  ),
                ),
              ],
            ],
          ),
          const SizedBox(height: 14),
          Container(
            height: 7,
            decoration: BoxDecoration(
              color: colors.onDeepPrimary.withValues(alpha: 0.16),
              borderRadius: radii.rFull,
            ),
            child: Align(
              alignment: Alignment.centerLeft,
              child: FractionallySizedBox(
                widthFactor: ratio,
                child: Container(
                  key: progressFillKey,
                  decoration: BoxDecoration(
                    gradient: gradients.warmBar,
                    borderRadius: radii.rFull,
                  ),
                ),
              ),
            ),
          ),
          if (leftNote != null || rightNote != null) ...[
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: Text(
                    leftNote ?? '',
                    style: type.caption.copyWith(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w600,
                      color: colors.onDeepTertiary,
                    ),
                  ),
                ),
                if (rightNote != null)
                  Flexible(
                    child: Text(
                      rightNote!,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      textAlign: TextAlign.right,
                      style: type.caption.copyWith(
                        fontSize: 11.5,
                        fontWeight: FontWeight.w600,
                        color: colors.onDeepTertiary,
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
