import 'package:flutter/material.dart';

import '../tokens/tokens.dart';
import 'press_scale.dart';

/// A31 `accent` 语义档：图标与图标底的语义色，不暴露像素色。
enum EntryAccent { money, ai, health, warm }

/// A31 entry（功能入口行卡）：账本页「手动记一笔 / AI 自动记账」等同级双入口。
///
/// 副文案体现 AI 动态（如「本月已自动记 42 笔」），调用方不得传静态说明。
class EntryCard extends StatelessWidget {
  const EntryCard({
    super.key,
    required this.title,
    required this.subtitle,
    required this.icon,
    this.accent = EntryAccent.money,
    this.onTap,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final EntryAccent accent;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    return PressScale(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radii.rMd,
          boxShadow: elevation.card,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                color: _tileColor(colors),
                borderRadius: BorderRadius.circular(radii.iconTile(38)),
              ),
              child: Icon(icon, size: 19, color: _accentColor(colors)),
            ),
            const SizedBox(height: 10),
            Text(
              title,
              style: type.caption.copyWith(
                color: colors.ink,
                fontSize: 13.5,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              subtitle,
              style: type.caption.copyWith(color: colors.ink3),
            ),
          ],
        ),
      ),
    );
  }

  Color _accentColor(AppColors colors) => switch (accent) {
        EntryAccent.money => colors.money,
        EntryAccent.ai => colors.aiPrimary,
        EntryAccent.health => colors.health,
        EntryAccent.warm => colors.warm,
      };

  Color _tileColor(AppColors colors) => switch (accent) {
        EntryAccent.money => colors.tileMoney,
        EntryAccent.ai => colors.tileAi,
        EntryAccent.health => colors.tileHealth,
        EntryAccent.warm => colors.tileWarm,
      };
}
