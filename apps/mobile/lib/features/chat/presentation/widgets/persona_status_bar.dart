import 'package:flutter/material.dart';

import '../../../../app/theme/theme_context.dart';
import '../../../../design_system/components/mode_selector.dart';
import '../../../../design_system/orb/orb.dart';

/// 对话页头部人格状态栏（B2 头部；沉浸式下左侧带返回键）。
class PersonaStatusBar extends StatelessWidget {
  const PersonaStatusBar({
    super.key,
    required this.mode,
    this.online = true,
    this.onBack,
    this.onOpenModeSheet,
  });

  final RoleMode mode;
  final bool online;
  final VoidCallback? onBack;
  final VoidCallback? onOpenModeSheet;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 12, 18, 8),
      child: Row(
        children: [
          if (onBack != null) ...[
            GestureDetector(
              onTap: onBack,
              behavior: HitTestBehavior.opaque,
              child: SizedBox(
                width: 30,
                height: 30,
                child: Center(
                  child: Icon(
                    AppIcons.chevronLeft,
                    size: 18,
                    color: colors.ink2,
                  ),
                ),
              ),
            ),
            const SizedBox(width: 8),
          ],
          const Orb(size: OrbSize.md),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('亚丝娜',
                    style: type.sectionTitle.copyWith(color: colors.ink)),
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Container(
                      width: 6,
                      height: 6,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: online ? colors.health : colors.ink3,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '${online ? '在线' : '离线'} · ${mode.label} 模式',
                      style: type.label.copyWith(
                        fontSize: 11.5,
                        letterSpacing: 0,
                        color: online ? colors.health : colors.ink3,
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          _ModeSwitchChip(onTap: onOpenModeSheet),
        ],
      ),
    );
  }
}

class _ModeSwitchChip extends StatelessWidget {
  const _ModeSwitchChip({this.onTap});

  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 11),
        decoration: BoxDecoration(
          color: colors.tagPreferenceBg,
          borderRadius: radii.rFull,
          border: Border.all(color: colors.aiPrimary.withValues(alpha: 0.22)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(AppIcons.slidersHorizontal, size: 11, color: colors.aiPrimary),
            const SizedBox(width: 5),
            Text('切换模式',
                style: type.label
                    .copyWith(color: colors.aiPrimary, fontSize: 11.5)),
          ],
        ),
      ),
    );
  }
}
