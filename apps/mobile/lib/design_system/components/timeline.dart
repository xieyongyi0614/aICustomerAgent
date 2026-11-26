import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

/// A37 timeline 单项。
///
/// `isUpcoming` 由**调用方**保证落在末行：组件不排序、不判定末项（规格纪律）。
class TimelineItem {
  const TimelineItem({
    required this.icon,
    required this.title,
    this.accent,
    this.subtitle,
    this.valueText,
    this.isUpcoming = false,
  });

  final IconData icon;
  final String title;
  final Color? accent;
  final String? subtitle;
  final String? valueText;
  final bool isUpcoming;
}

/// A37 timeline（记录时间线）：白卡 + 行分割线（末行无分割线）+ 未发生态。
class Timeline extends StatelessWidget {
  const Timeline({super.key, required this.items});

  static ValueKey<String> rowKey(int index) => ValueKey('timeline-row-$index');

  static ValueKey<String> valueKey(int index) =>
      ValueKey('timeline-value-$index');

  final List<TimelineItem> items;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 18),
      decoration: BoxDecoration(color: colors.surface, borderRadius: radii.rLg),
      child: Column(
        children: [
          for (var index = 0; index < items.length; index++)
            _row(context, items[index], index, index == items.length - 1),
        ],
      ),
    );
  }

  Widget _row(
    BuildContext context,
    TimelineItem item,
    int index,
    bool isLast,
  ) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final accent = item.accent ?? colors.aiPrimary;
    final upcoming = item.isUpcoming;
    return Container(
      key: rowKey(index),
      padding: const EdgeInsets.symmetric(vertical: 14),
      decoration: isLast
          ? null
          : BoxDecoration(border: Border(bottom: BorderSide(color: colors.line))),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Container(
            width: 26,
            height: 26,
            decoration: BoxDecoration(
              color: upcoming ? colors.fillSubtle : accent.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(radii.iconTile(26)),
            ),
            child: Icon(
              item.icon,
              size: 14,
              color: upcoming ? colors.inkOnSoon : accent,
            ),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  item.title,
                  style: type.rowTitle.copyWith(
                    color: upcoming ? colors.inkOnSoon : colors.ink,
                  ),
                ),
                if (item.subtitle != null) ...[
                  const SizedBox(height: 3),
                  Text(
                    item.subtitle!,
                    style: type.caption.copyWith(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w400,
                      color: colors.ink3,
                    ),
                  ),
                ],
              ],
            ),
          ),
          if (item.valueText != null)
            Text(
              item.valueText!,
              key: valueKey(index),
              style: upcoming
                  ? type.caption.copyWith(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: colors.inkOnSoon,
                      fontFeatures: AppTypography.tabular,
                    )
                  : type.rowTitle.copyWith(
                      fontWeight: FontWeight.w700,
                      color: colors.ink,
                      fontFeatures: AppTypography.tabular,
                    ),
            ),
        ],
      ),
    );
  }
}
