import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/state/dynamic_tab.dart';
import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';

/// 长按生活模块卡弹出的「设为动态」面板：六选一，选中即写 provider 并落盘。
class DynamicModuleSheet extends ConsumerWidget {
  const DynamicModuleSheet({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.colors;
    final type = context.typography;
    final current = ref.watch(dynamicModuleProvider);
    return Padding(
      padding: EdgeInsets.only(
        left: 18,
        right: 18,
        top: 16,
        bottom: MediaQuery.of(context).padding.bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('设为动态', style: type.sectionTitle),
          const SizedBox(height: 6),
          Text(
            '选中的模块会出现在底部导航第 2 位，点开就是它的完整页面',
            style: type.caption.copyWith(color: colors.ink3, height: 1.5),
          ),
          const SizedBox(height: 14),
          SettingGroup(
            children: [
              for (final module in LifeModule.values)
                SettingRow(
                  title: module.label,
                  icon: module.icon,
                  iconColor: colors.aiPrimary,
                  showDivider: module != LifeModule.values.last,
                  trailing: module == current
                      ? Icon(AppIcons.check, size: 18, color: colors.aiPrimary)
                      : null,
                  onTap: () {
                    ref.read(dynamicModuleProvider.notifier).select(module);
                    Navigator.of(context).pop();
                  },
                ),
            ],
          ),
        ],
      ),
    );
  }
}
