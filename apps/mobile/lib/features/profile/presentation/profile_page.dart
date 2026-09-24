import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/cards.dart';
import '../../../design_system/components/mode_selector.dart';
import '../../../design_system/components/rows.dart';
import '../../../design_system/orb/orb.dart';

/// B8 #profile 我的：用户卡 + 人格卡 + 设置组。
class ProfilePage extends StatelessWidget {
  const ProfilePage({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: context.spacing.screenPadding,
          children: [
            // 用户卡
            AppCard(
              child: Row(
                children: [
                  Container(
                    width: 54,
                    height: 54,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: context.gradients.avatar,
                    ),
                    child: Icon(Icons.person, size: 26, color: colors.avatarText),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('你', style: type.sectionTitle),
                        Text('相识 42 天 · 关系 Lv.3',
                            style: type.caption.copyWith(color: colors.ink2)),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),
            // AI 人格卡（深夜紫）
            Container(
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(
                gradient: context.gradients.deepPersona,
                borderRadius: context.radii.rLg,
                boxShadow: context.elevation.deep,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Orb(size: OrbSize.md),
                      const SizedBox(width: 12),
                      Text('亚丝娜',
                          style: type.sectionTitle
                              .copyWith(color: colors.onDeepPrimary)),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text('温柔可靠 · 会主动关心你的生活',
                      style: type.sub.copyWith(color: colors.onDeepSecondary)),
                  const ModeSelector(
                    value: RoleMode.defaultMode,
                    onChanged: _noopMode,
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),
            SettingGroup(
              children: [
                SettingRow(
                  title: '设备连接',
                  subtitle: '● 小米手环 9 Pro',
                  icon: Icons.watch,
                  trailing: Text('已连接',
                      style: type.caption.copyWith(color: colors.health)),
                ),
                SettingRow(
                  title: '健康数据授权',
                  subtitle: '单独同意 · 可随时关闭',
                  icon: Icons.favorite,
                  onTap: () => context.go('/health/consent'),
                ),
                SettingRow(
                  title: '记忆与隐私',
                  subtitle: '可导出、可清空',
                  icon: Icons.lock,
                  onTap: () => context.go('/profile/privacy'),
                  showDivider: false,
                ),
                SettingRow(
                  title: '设备配对',
                  subtitle: '绑定这台设备',
                  icon: Icons.link,
                  onTap: () => context.go('/profile/pairing'),
                  showDivider: false,
                ),
              ],
            ),
            SettingGroup(
              children: [
                SettingRow(
                  title: '早间简报',
                  subtitle: '设定时刻 08:00',
                  icon: Icons.wb_sunny,
                  trailing: AppToggle(value: true, onChanged: (_) {}),
                ),
                SettingRow(
                  title: '晚间总结',
                  subtitle: '设定时刻 21:30',
                  icon: Icons.nightlight,
                  trailing: AppToggle(value: true, onChanged: (_) {}),
                ),
                SettingRow(
                  title: '主动关怀',
                  subtitle: '异常时提醒，不刷存在感',
                  icon: Icons.volunteer_activism,
                  trailing: AppToggle(value: false, onChanged: (_) {}),
                  showDivider: false,
                ),
              ],
            ),
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }
}

void _noopMode(RoleMode mode) {}
