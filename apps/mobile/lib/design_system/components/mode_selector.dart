import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

enum RoleMode { professional, defaultMode, immersive }

extension RoleModeX on RoleMode {
  String get id => switch (this) {
        RoleMode.professional => 'professional',
        RoleMode.defaultMode => 'default',
        RoleMode.immersive => 'immersive',
      };

  String get label => switch (this) {
        RoleMode.professional => 'Professional',
        RoleMode.defaultMode => 'Default',
        RoleMode.immersive => 'Immersive',
      };

  /// 中文副标真源 principles.md §5.1
  String get subtitle => switch (this) {
        RoleMode.professional => '高效工作',
        RoleMode.defaultMode => '日常陪伴',
        RoleMode.immersive => '沉浸角色',
      };

  static RoleMode fromId(String? raw) => switch (raw) {
        'professional' => RoleMode.professional,
        'immersive' => RoleMode.immersive,
        _ => RoleMode.defaultMode,
      };
}

/// A28 mode-row / mode-opt：三档切换（深色卡内，与我的页共用）。
class ModeSelector extends StatelessWidget {
  const ModeSelector({
    super.key,
    required this.value,
    required this.onChanged,
  });

  final RoleMode value;
  final ValueChanged<RoleMode> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    return Padding(
      padding: const EdgeInsets.only(top: 15),
      child: Row(
        children: [
          for (final mode in RoleMode.values) ...[
            if (mode != RoleMode.values.first) const SizedBox(width: 8),
            Expanded(
              child: GestureDetector(
                onTap: () => onChanged(mode),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 4),
                  decoration: BoxDecoration(
                    color: value == mode
                        ? colors.surface
                        : colors.onDeepSecondary.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Column(
                    children: [
                      Text(
                        mode.label,
                        style: type.caption.copyWith(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: value == mode
                              ? colors.onWhitePill
                              : colors.onDeepSecondary,
                        ),
                      ),
                      Text(
                        mode.subtitle,
                        style: type.tabLabel.copyWith(
                          fontSize: 10.5,
                          fontWeight: FontWeight.w400,
                          color: (value == mode
                                  ? colors.onWhitePill
                                  : colors.onDeepSecondary)
                              .withValues(alpha: 0.7),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
