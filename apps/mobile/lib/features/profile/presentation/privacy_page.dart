import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/network/dio_client.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/components/cards.dart';
import '../../../design_system/components/rows.dart';

/// 隐私与授权：导出 / 清空。清空需二次确认。
class ProfilePrivacyPage extends StatelessWidget {
  const ProfilePrivacyPage({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      appBar: AppBar(title: const Text('隐私与授权')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 40),
        children: [
          SettingGroup(
            children: [
              SettingRow(
                title: '导出我的数据',
                subtitle: '生成一份完整备份',
                icon: AppIcons.download,
                onTap: () async {
                  final dio = createDio();
                  await dio.get('/life/export');
                },
                showDivider: false,
              ),
            ],
          ),
          PrivacyNote(
            child: Text(
              '你的数据由你控制：可导出、可逐条遗忘，也可一键清空。清空后服务端与本地缓存同步删除。',
            ),
          ),
          const SizedBox(height: 24),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: colors.warm),
            onPressed: () => _confirmWipe(context),
            child: const Text('一键清空我的数据'),
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

  void _confirmWipe(BuildContext context) {
    showDialog<void>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          title: const Text('确认清空？'),
          content: const Text('清空后无法恢复，服务端与本地都会删除。'),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: const Text('再想想'),
            ),
            TextButton(
              onPressed: () async {
                Navigator.of(ctx).pop();
                await _wipe(context);
              },
              child: const Text('确认清空'),
            ),
          ],
        );
      },
    );
  }

  /// 承诺「服务端与本地都会删除」就必须两边都做到：服务端失败时停下并明说，
  /// 成功后清掉本机偏好与各域私有键（album.* 等），不再静默吞错。
  Future<void> _wipe(BuildContext context) async {
    final dio = createDio();
    try {
      await dio.delete('/life/data');
    } catch (_) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('服务端清空失败，请检查网络后重试；本地数据还没有删除'),
        ),
      );
      return;
    }
    final prefs = await PrefsStore.load();
    await prefs.clearBusinessData();
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('已清空服务端与本机数据')),
    );
  }
}
