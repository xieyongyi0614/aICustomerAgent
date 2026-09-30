import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

/// A33 stat（统计迷你卡）
class LedgerStatCard extends StatelessWidget {
  const LedgerStatCard({
    super.key,
    required this.value,
    required this.label,
    this.unit,
  });

  final String value;
  final String label;
  final String? unit;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13, horizontal: 12),
      decoration: BoxDecoration(color: colors.surface, borderRadius: radii.rMd),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.baseline,
            textBaseline: TextBaseline.alphabetic,
            children: [
              Text(
                value,
                style: type.amountHero
                    .copyWith(fontSize: 19, letterSpacing: -0.38),
              ),
              if (unit != null) ...[
                const SizedBox(width: 3),
                Text(
                  unit!,
                  style: type.caption.copyWith(
                    color: colors.ink3,
                    fontWeight: FontWeight.w400,
                  ),
                ),
              ],
            ],
          ),
          const SizedBox(height: 4),
          Text(
            label,
            style: type.caption.copyWith(
              color: colors.ink3,
              fontWeight: FontWeight.w400,
            ),
          ),
        ],
      ),
    );
  }
}

/// A33 confirm 按钮语义档：`primary` = 确认（health 底白字），`ghost` = 修改 / 忽略。
enum LedgerActionKind { primary, ghost }

class LedgerConfirmAction {
  const LedgerConfirmAction({
    required this.label,
    required this.onTap,
    this.kind = LedgerActionKind.ghost,
  });

  final String label;
  final VoidCallback? onTap;
  final LedgerActionKind kind;
}

/// A33 confirm（待确认行）：列表卡内一行，右对齐按钮组。
class LedgerConfirmRow extends StatelessWidget {
  const LedgerConfirmRow({
    super.key,
    required this.title,
    required this.judgment,
    this.icon = AppIcons.sparkles,
    this.actions = const [],
    this.showDivider = true,
  });

  final String title;
  final String judgment;
  final IconData icon;
  final List<LedgerConfirmAction> actions;
  final bool showDivider;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13),
      decoration: BoxDecoration(
        border:
            showDivider ? Border(bottom: BorderSide(color: colors.line)) : null,
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: colors.tileMoney,
              borderRadius: BorderRadius.circular(radii.iconTile(36)),
            ),
            child: Icon(icon, size: 18, color: colors.money),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: type.rowTitle.copyWith(color: colors.ink),
                ),
                const SizedBox(height: 2),
                Text(
                  judgment,
                  style: type.caption.copyWith(
                    fontSize: 11.5,
                    color: colors.ink3,
                    fontWeight: FontWeight.w400,
                    letterSpacing: 0,
                  ),
                ),
              ],
            ),
          ),
          for (final action in actions) ...[
            const SizedBox(width: 8),
            _action(context, action),
          ],
        ],
      ),
    );
  }

  Widget _action(BuildContext context, LedgerConfirmAction action) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final primary = action.kind == LedgerActionKind.primary;
    return GestureDetector(
      onTap: action.onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 13),
        decoration: BoxDecoration(
          color: primary ? colors.health : colors.surface,
          borderRadius: radii.rFull,
          border: primary ? null : Border.all(color: colors.line),
        ),
        child: Text(
          action.label,
          style: type.label.copyWith(
            fontSize: 12.5,
            letterSpacing: 0,
            fontWeight: FontWeight.w600,
            color: primary ? colors.onDeepPrimary : colors.ink2,
          ),
        ),
      ),
    );
  }
}

/// A33 rule（学会的规则行）：关键词 → 目标分类，来源缺省时不渲染占位。
class LedgerRuleRow extends StatelessWidget {
  const LedgerRuleRow({
    super.key,
    required this.keyword,
    required this.target,
    this.sourceNote,
  });

  final String keyword;
  final String target;
  final String? sourceNote;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 11),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.symmetric(vertical: 5, horizontal: 10),
            decoration: BoxDecoration(
              color: colors.fillSubtle,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              keyword,
              style: type.caption.copyWith(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: colors.ink,
              ),
            ),
          ),
          const SizedBox(width: 8),
          Icon(AppIcons.chevronRight, size: 14, color: colors.ink3),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              target,
              style: type.caption.copyWith(
                fontSize: 13.5,
                fontWeight: FontWeight.w600,
                color: colors.ink,
              ),
            ),
          ),
          if (sourceNote != null)
            Text(
              sourceNote!,
              style: type.caption.copyWith(
                color: colors.ink3,
                fontWeight: FontWeight.w400,
              ),
            ),
        ],
      ),
    );
  }
}
