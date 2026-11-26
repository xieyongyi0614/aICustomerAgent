import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

/// A35 type-scroll 单项：`accent` 为该类型语义色，选中态描边由它派生。
class TypeScrollItem {
  const TypeScrollItem({
    required this.key,
    required this.label,
    required this.icon,
    required this.accent,
  });

  final String key;
  final String label;
  final IconData icon;
  final Color accent;
}

/// A35 type-scroll（类型胶囊横滑）：选中 = 该类型语义色 55% 描边。
class TypeScroll extends StatelessWidget {
  const TypeScroll({
    super.key,
    required this.items,
    this.selectedKey,
    this.onSelected,
  });

  static ValueKey<String> itemKey(String key) => ValueKey('type-scroll-$key');

  final List<TypeScrollItem> items;
  final String? selectedKey;
  final ValueChanged<String>? onSelected;

  @override
  Widget build(BuildContext context) {
    return ScrollConfiguration(
      behavior: ScrollConfiguration.of(context).copyWith(scrollbars: false),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 1),
        child: Row(
          children: [
            for (var index = 0; index < items.length; index++) ...[
              if (index > 0) const SizedBox(width: 9),
              _pill(context, items[index]),
            ],
          ],
        ),
      ),
    );
  }

  Widget _pill(BuildContext context, TypeScrollItem item) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    final selected = item.key == selectedKey;
    return GestureDetector(
      onTap: onSelected == null ? null : () => onSelected!(item.key),
      child: Container(
        key: itemKey(item.key),
        padding: const EdgeInsets.symmetric(horizontal: 15, vertical: 9),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radii.rFull,
          boxShadow: elevation.card,
          border: Border.all(
            width: 1.5,
            color: selected
                ? item.accent.withValues(alpha: 0.55)
                : colors.transparent,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              item.icon,
              size: 15,
              color: selected ? item.accent : colors.ink2,
            ),
            const SizedBox(width: 6),
            Text(
              item.label,
              style: type.caption.copyWith(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: selected ? colors.ink : colors.ink2,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
