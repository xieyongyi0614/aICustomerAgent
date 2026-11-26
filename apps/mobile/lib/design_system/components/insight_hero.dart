import 'package:flutter/material.dart';

import '../orb/orb.dart';
import '../tokens/tokens.dart';

/// B6 健康状态 Hero（`insight-hero`）：Orb md + 状态语 17px/700 + 可选评分标签 + 正文。
///
/// 底为 `insightHero` 渐变 + aiPrimary 14% 描边 —— 这是**健康域唯一的 AI 结论块**，
/// 必须排在原始指标之前（红线 4）。无真实评分时 `tag` 传 null，不得编造分数。
class InsightHero extends StatelessWidget {
  const InsightHero({
    super.key,
    required this.title,
    required this.body,
    this.tag,
  });

  final String title;
  final String body;
  final String? tag;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    final gradients = Theme.of(context).extension<AppGradients>()!;
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        gradient: gradients.insightHero,
        borderRadius: radii.rLg,
        border: Border.all(color: colors.aiPrimary.withValues(alpha: 0.14)),
        boxShadow: elevation.card,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Orb(size: OrbSize.md),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  title,
                  style: type.sectionTitle.copyWith(fontSize: 17),
                ),
              ),
              if (tag != null)
                Container(
                  padding: const EdgeInsets.symmetric(
                    vertical: 3,
                    horizontal: 9,
                  ),
                  decoration: BoxDecoration(
                    color: colors.tileHealth,
                    borderRadius: radii.rFull,
                  ),
                  child: Text(
                    tag!,
                    style: type.caption.copyWith(
                      fontSize: 11,
                      color: colors.health,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            body,
            style: type.body.copyWith(
              fontSize: 13.5,
              height: 1.75,
              color: colors.bodyOnInsight,
            ),
          ),
        ],
      ),
    );
  }
}
