import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/state/persona_mode.dart';
import '../../../app/theme/theme_context.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';
import '../data/auth_repository.dart';

/// B8 #profile 我的：相识卡 + 人格卡 + 设置组 + 主动关怀 + 退出登录。
class ProfilePage extends ConsumerStatefulWidget {
  const ProfilePage({super.key});

  @override
  ConsumerState<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends ConsumerState<ProfilePage> {
  final _auth = AuthRepository();
  String? _nickname;
  int _days = 1;

  @override
  void initState() {
    super.initState();
    _loadIdentity();
  }

  Future<void> _loadIdentity() async {
    try {
      final prefs = await PrefsStore.load();
      final paired = await _auth.hasToken();
      final raw = prefs.firstUsedAt();
      var firstUsedAt = raw == null ? null : DateTime.tryParse(raw);
      if (paired && firstUsedAt == null) {
        await prefs.markLoginSeen();
        firstUsedAt = DateTime.now();
      }
      final days = firstUsedAt == null
          ? 1
          : DateTime.now().difference(firstUsedAt).inDays + 1;
      if (!mounted) return;
      setState(() {
        _nickname = prefs.nickname();
        _days = days;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _days = 1);
    }
  }

  void _noticePersonaEdit() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        behavior: SnackBarBehavior.floating,
        content: Text('人格编辑还没上线，先用下面的模式切换相处方式吧'),
      ),
    );
  }

  Future<void> _confirmSignOut() async {
    final colors = context.colors;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('退出登录'),
        content: const Text('退出后需要重新登录或配对才能继续同步，本机数据不会丢失。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text(
              '退出登录',
              style: TextStyle(color: colors.danger),
            ),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await _auth.signOut();
    final prefs = await PrefsStore.load();
    await prefs.clearIdentity();
    if (!mounted) return;
    context.go('/login');
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    final mode = ref.watch(personaModeProvider);
    final name = (_nickname == null || _nickname!.isEmpty) ? '你' : _nickname!;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: context.spacing.screenPadding,
          children: [
            Row(
              children: [
                Container(
                  width: 54,
                  height: 54,
                  alignment: Alignment.center,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: context.gradients.avatar,
                  ),
                  child: Text(
                    name.substring(0, 1),
                    style: type.sectionTitle.copyWith(
                      fontSize: 20,
                      color: colors.avatarText,
                    ),
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(name, style: type.title.copyWith(fontSize: 18)),
                      const SizedBox(height: 3),
                      Text(
                        '与亚丝娜相识 $_days 天',
                        style: type.sub.copyWith(
                          fontSize: 12.5,
                          color: colors.ink2,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 18),
            Container(
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(
                gradient: context.gradients.deepPersona,
                borderRadius: radii.rLg,
                boxShadow: context.elevation.deep,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Orb(size: OrbSize.md),
                      const SizedBox(width: 13),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '亚丝娜',
                              style: type.sectionTitle.copyWith(
                                color: colors.onDeepPrimary,
                              ),
                            ),
                            const SizedBox(height: 3),
                            Text(
                              '温柔可靠 · 会主动关心你的生活',
                              style: type.sub.copyWith(
                                fontSize: 12,
                                color: colors.onDeepSecondary,
                              ),
                            ),
                          ],
                        ),
                      ),
                      GestureDetector(
                        onTap: _noticePersonaEdit,
                        behavior: HitTestBehavior.opaque,
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            vertical: 6,
                            horizontal: 13,
                          ),
                          decoration: BoxDecoration(
                            color:
                                colors.onDeepPrimary.withValues(alpha: 0.14),
                            borderRadius: radii.rFull,
                          ),
                          child: Text(
                            '编辑人格',
                            style: type.label.copyWith(
                              fontSize: 12,
                              letterSpacing: 0,
                              color: colors.onDeepPrimary,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                  ModeSelector(
                    value: mode,
                    onChanged: (m) =>
                        ref.read(personaModeProvider.notifier).set(m),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),
            SettingGroup(
              children: [
                SettingRow(
                  title: '设备连接',
                  subtitle: '健康数据实时同步',
                  icon: AppIcons.watch,
                  iconBg: colors.tileHealth,
                  iconColor: colors.health,
                  trailing: Icon(
                    AppIcons.chevronRight,
                    size: 16,
                    color: colors.ink3,
                  ),
                  onTap: () => context.go('/health'),
                ),
                SettingRow(
                  title: '健康数据授权',
                  subtitle: '单独同意 · 可随时关闭',
                  icon: AppIcons.shield,
                  iconBg: colors.tileInfo,
                  iconColor: colors.aiBlue,
                  trailing: Icon(
                    AppIcons.chevronRight,
                    size: 16,
                    color: colors.ink3,
                  ),
                  onTap: () => context.go('/health/consent'),
                ),
                SettingRow(
                  title: '记忆管理',
                  subtitle: '查看、编辑、遗忘',
                  icon: AppIcons.brain,
                  iconBg: colors.tileAi,
                  iconColor: colors.aiPrimary,
                  trailing: Icon(
                    AppIcons.chevronRight,
                    size: 16,
                    color: colors.ink3,
                  ),
                  onTap: () => context.go('/memory'),
                ),
                SettingRow(
                  title: '隐私设置',
                  subtitle: '可导出 · 可清空',
                  icon: AppIcons.lock,
                  iconBg: colors.tileMoney,
                  iconColor: colors.tagHabitFg,
                  trailing: Icon(
                    AppIcons.chevronRight,
                    size: 16,
                    color: colors.ink3,
                  ),
                  onTap: () => context.go('/profile/privacy'),
                ),
                SettingRow(
                  title: '设备配对',
                  subtitle: '绑定这台设备',
                  icon: AppIcons.link,
                  trailing: Icon(
                    AppIcons.chevronRight,
                    size: 16,
                    color: colors.ink3,
                  ),
                  onTap: () => context.go('/profile/pairing'),
                  showDivider: false,
                ),
              ],
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(2, 6, 2, 11),
              child: Text('主动关怀', style: type.sectionTitle),
            ),
            SettingGroup(
              children: [
                SettingRow(
                  title: '早间简报',
                  subtitle: '每天 08:00 · 「我整理了你的今天」',
                  trailing: AppToggle(value: true, onChanged: (_) {}),
                ),
                SettingRow(
                  title: '晚间总结',
                  subtitle: '每天 21:30 · 回顾今天，安顿明天',
                  trailing: AppToggle(value: true, onChanged: (_) {}),
                ),
                SettingRow(
                  title: '状态异常提醒',
                  subtitle: '睡眠 / 心率出现异常趋势时主动告知',
                  trailing: AppToggle(value: false, onChanged: (_) {}),
                  showDivider: false,
                ),
              ],
            ),
            GestureDetector(
              onTap: _confirmSignOut,
              behavior: HitTestBehavior.opaque,
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 15),
                alignment: Alignment.center,
                child: Text(
                  '退出登录',
                  style: type.body.copyWith(color: colors.danger),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text(
                '朝夕 v0.1.0 (MVP) · Personal AI OS 的第一步',
                textAlign: TextAlign.center,
                style: type.sub.copyWith(color: colors.ink2),
              ),
            ),
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }
}
