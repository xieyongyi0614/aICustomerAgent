import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/components/cards.dart';
import '../../../design_system/components/rows.dart';

/// APP-025 健康授权与免责：单独同意记录持久化，无论健康模块是否上线都交付。
class HealthConsentPage extends StatefulWidget {
  const HealthConsentPage({super.key});

  @override
  State<HealthConsentPage> createState() => _HealthConsentPageState();
}

class _HealthConsentPageState extends State<HealthConsentPage> {
  bool _granted = false;
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final prefs = await PrefsStore.load();
    if (!mounted) return;
    setState(() {
      _granted = prefs.healthConsentGranted();
      _loaded = true;
    });
  }

  Future<void> _toggle(bool granted) async {
    final prefs = await PrefsStore.load();
    await prefs.setHealthConsentGranted(granted);
    if (!mounted) return;
    setState(() => _granted = granted);
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      appBar: AppBar(title: const Text('健康数据授权')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 40),
        children: [
          Text(
            '你可以单独同意健康数据读取，用于趋势参考。随时可关闭。',
            style: type.body.copyWith(color: colors.ink2, height: 1.6),
          ),
          const SizedBox(height: 16),
          SettingGroup(
            children: [
              SettingRow(
                title: '读取健康数据',
                subtitle: _loaded
                    ? (_granted ? '已同意 · 可随时关闭' : '未同意 · 开启后用于健康趋势')
                    : '读取同意状态…',
                icon: Icons.favorite,
                iconBg: colors.tileHealth,
                iconColor: colors.health,
                trailing: _loaded
                    ? AppToggle(value: _granted, onChanged: _toggle)
                    : const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                showDivider: false,
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            '同意后，数据读取发生在设备端的系统健康互联（Health Connect）中；'
            '关闭同意不会删除已同步到健康互联的数据，可在系统设置中管理。',
            style: type.caption.copyWith(color: colors.ink3, height: 1.5),
          ),
          PrivacyNote(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('隐私说明：健康数据仅用于生成趋势与建议，不会用于医疗诊断。'),
                SizedBox(height: 8),
                Text('非医疗建议，请咨询医生。'),
              ],
            ),
          ),
          const SizedBox(height: 12),
          Text(
            '非医疗建议，请咨询医生',
            textAlign: TextAlign.center,
            style: type.caption.copyWith(color: colors.ink3),
          ),
        ],
      ),
    );
  }
}
