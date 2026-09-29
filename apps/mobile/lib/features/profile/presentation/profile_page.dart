import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/state/persona_mode.dart';
import '../../../app/theme/theme_context.dart';
import '../../../core/notify/local_brief_notifier.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';
import '../data/auth_repository.dart';
import '../data/care_prefs_repository.dart';

/// B8 #profile 我的：相识卡 + 人格卡 + 设置组 + 主动关怀 + 退出登录。
class ProfilePage extends ConsumerStatefulWidget {
  const ProfilePage({super.key});

  @override
  ConsumerState<ProfilePage> createState() => _ProfilePageState();
}

class _ProfilePageState extends ConsumerState<ProfilePage> {
  final _auth = AuthRepository();
  final _careRepo = CarePrefsRepository();
  String? _nickname;
  int _days = 1;
  CarePrefs? _care;
  bool _careBusy = false;

  @override
  void initState() {
    super.initState();
    _loadIdentity();
    _loadCare();
  }

  Future<void> _loadCare() async {
    try {
      final care = await _careRepo.fetch();
      if (!mounted) return;
      setState(() => _care = care);
    } catch (_) {
      if (!mounted) return;
      setState(() => _care = null);
    }
  }

  /// 后端 PUT 是整体替换：先取当前值合并，city 原样回传避免清空天气定位。
  Future<void> _toggleBrief({required bool evening, required bool on}) async {
    if (_careBusy) return;
    setState(() => _careBusy = true);
    try {
      final current = await _careRepo.fetch();
      final morningAt = evening
          ? current.morningAt
          : (on ? (current.morningAt ?? '08:00') : null);
      final eveningAt = !evening
          ? current.eveningAt
          : (on ? (current.eveningAt ?? '21:30') : null);
      final saved = await _careRepo.save(
        morningAt: morningAt,
        eveningAt: eveningAt,
        city: current.city,
      );
      if (!mounted) return;
      setState(() => _care = saved);
      await _rescheduleNotify(saved);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('保存失败，请检查网络后重试')),
      );
    } finally {
      if (mounted) setState(() => _careBusy = false);
    }
  }

  Future<void> _rescheduleNotify(CarePrefs care) async {
    final notifier = LocalBriefNotifier.shared;
    if (notifier == null) return;
    await notifier.cancelAll();
    final morning = _parseHHmm(care.morningAt);
    if (morning != null) {
      await notifier.scheduleDaily(hour: morning.$1, minute: morning.$2, evening: false);
    }
    final evening = _parseHHmm(care.eveningAt);
    if (evening != null) {
      await notifier.scheduleDaily(hour: evening.$1, minute: evening.$2, evening: true);
    }
  }

  (int, int)? _parseHHmm(String? hhmm) {
    if (hhmm == null || !hhmm.contains(':')) return null;
    final parts = hhmm.split(':');
    final h = int.tryParse(parts[0]);
    final m = int.tryParse(parts[1]);
    if (h == null || m == null || h < 0 || h > 23 || m < 0 || m > 59) return null;
    return (h, m);
  }

  Future<void> _loadIdentity() async {
    try {
      final prefs = await PrefsStore.load();
      final loggedIn = await _auth.hasToken();
      final raw = prefs.firstUsedAt();
      var firstUsedAt = raw == null ? null : DateTime.tryParse(raw);
      if (loggedIn && firstUsedAt == null) {
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
        content: const Text('退出后需要重新登录才能继续同步，本机数据不会丢失。'),
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
                  subtitle: (_care?.morningAt) == null
                      ? '已关闭 · 开启后每天定时推送'
                      : '每天 ${_care!.morningAt} · 「我整理了你的今天」',
                  trailing: _care == null
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : AppToggle(
                          value: _care!.morningOn,
                          onChanged: (_) => _toggleBrief(
                            evening: false,
                            on: !_care!.morningOn,
                          ),
                        ),
                ),
                SettingRow(
                  title: '晚间总结',
                  subtitle: (_care?.eveningAt) == null
                      ? '已关闭 · 开启后每天定时推送'
                      : '每天 ${_care!.eveningAt} · 回顾今天，安顿明天',
                  trailing: _care == null
                      ? const SizedBox(
                          width: 20,
                          height: 20,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : AppToggle(
                          value: _care!.eveningOn,
                          onChanged: (_) => _toggleBrief(
                            evening: true,
                            on: !_care!.eveningOn,
                          ),
                        ),
                ),
                SettingRow(
                  title: '状态异常提醒',
                  subtitle: '健康接入完成后开放（M4 门控）',
                  trailing: Text(
                    '即将开放',
                    style: type.caption.copyWith(color: colors.ink3),
                  ),
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
