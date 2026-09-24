import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/cards.dart';
import '../../../design_system/components/rows.dart';

/// APP-025 健康授权与免责：无论健康模块是否上线都必须交付。
class HealthConsentPage extends StatelessWidget {
  const HealthConsentPage({super.key});

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
                subtitle: '睡眠 / 心率 / 步数',
                icon: Icons.favorite,
                trailing: AppToggle(value: false, onChanged: (_) {}),
                showDivider: false,
              ),
            ],
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
