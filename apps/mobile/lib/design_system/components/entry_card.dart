import 'package:flutter/material.dart';

import '../tokens/tokens.dart';
import 'press_scale.dart';
import 'sparkle.dart';

/// A31 `accent` 语义档：图标与图标底的语义色，不暴露像素色。
enum EntryAccent { money, ai, health, warm }

/// A31 entry（功能入口行卡）：单张满宽 · 圆角 rMd · 内边距 14 · 按压 .97。
///
/// 布局：[图标方块 38px 圆角 13] 标题 13.5px/650 · 副文案 11px ink3 · 右侧 chevron 16px。
/// 用途：账本页「记一笔」单入口（键盘输入与说给亚丝娜是同一入口内的两种录入方式）——
/// **禁止**拆「手动 / AI 自动」两个并列入口（2026-09-30 IA 裁决）。
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
        child: Row(
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
            const SizedBox(width: 11),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: type.caption.copyWith(
                      color: colors.ink,
                      fontSize: 13.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    style: type.caption.copyWith(color: colors.ink3),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Icon(AppIcons.chevronRight, size: 16, color: colors.ink3),
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

/// A31 sync-link（次级文字链）：居中 · 12.5px/600 色 ink2 · [✦ 14px aiPrimary] + 文案 + chevron 14px。
///
/// 文案体现 AI 动态（如「本月已自动记 42 笔 · 同步与 AI 规则」），不写静态说明。
class SyncLink extends StatelessWidget {
  const SyncLink({super.key, required this.label, this.onTap});

  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Padding(
        padding: const EdgeInsets.only(top: 12),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            SparkleIcon(size: 14, color: colors.aiPrimary),
            const SizedBox(width: 5),
            Flexible(
              child: Text(
                label,
                style: type.label.copyWith(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 0,
                  color: colors.ink2,
                ),
              ),
            ),
            const SizedBox(width: 5),
            Icon(AppIcons.chevronRight, size: 14, color: colors.ink2),
          ],
        ),
      ),
    );
  }
}
