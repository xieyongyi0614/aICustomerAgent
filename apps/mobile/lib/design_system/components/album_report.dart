import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

/// A38 sug（AI 整理建议行）单项。
///
/// 纪律（skill `components.md:396`）：每行必须写清判定理由（`reason` 必填，
/// 不能只给类型名与数量）；数值成对出现（`countText` 张数 + `sizeText` 体积）。
class SuggestionRow {
  const SuggestionRow({
    required this.icon,
    required this.accent,
    required this.title,
    required this.reason,
    required this.countText,
    required this.sizeText,
    this.onTap,
  });

  final IconData icon;
  final Color accent;
  final String title;
  final String reason;
  final String countText;
  final String sizeText;
  final VoidCallback? onTap;
}

/// A38 sug 容器：白卡 rLg · 行内边距 15/0 · 分割线 line（末行无）· 整行可点。
class SuggestionCard extends StatelessWidget {
  const SuggestionCard({super.key, required this.rows});

  static ValueKey<String> rowKey(int index) =>
      ValueKey('suggestion-row-$index');

  final List<SuggestionRow> rows;

  @override
  Widget build(BuildContext context) {
    final radii = Theme.of(context).extension<AppRadii>()!;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 18),
      decoration: BoxDecoration(
        color: Theme.of(context).extension<AppColors>()!.surface,
        borderRadius: radii.rLg,
      ),
      child: Column(
        children: [
          for (var index = 0; index < rows.length; index++)
            _row(context, rows[index], index, index == rows.length - 1),
        ],
      ),
    );
  }

  Widget _row(
    BuildContext context,
    SuggestionRow row,
    int index,
    bool isLast,
  ) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    return Container(
      key: rowKey(index),
      decoration: isLast
          ? null
          : BoxDecoration(border: Border(bottom: BorderSide(color: colors.line))),
      child: InkWell(
        onTap: row.onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 15),
          child: Row(
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  color: row.accent.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(radii.iconTile(42)),
                ),
                child: Icon(row.icon, size: 20, color: row.accent),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      row.title,
                      style: type.rowTitle.copyWith(
                        fontSize: 14.5,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      row.reason,
                      style: type.caption.copyWith(
                        fontSize: 11.5,
                        color: colors.ink3,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 10),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    row.countText,
                    style: type.rowTitle.copyWith(
                      fontSize: 14.5,
                      fontWeight: FontWeight.w700,
                      fontFeatures: AppTypography.tabular,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    row.sizeText,
                    style: type.caption.copyWith(
                      fontSize: 11,
                      color: colors.ink3,
                      fontFeatures: AppTypography.tabular,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
