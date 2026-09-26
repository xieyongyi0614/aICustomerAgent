import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';

/// APP-024 健康页：四段 + 任意滚动位置常驻「非医疗建议」免责。
class HealthPage extends StatelessWidget {
  const HealthPage({super.key});

  static const disclaimer = '非医疗建议，请咨询医生';

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(18, 12, 18, 24),
                children: [
                  Row(
                    children: [
                      const Orb(size: OrbSize.sm),
                      const SizedBox(width: 10),
                      Text('健康', style: type.pageTitle),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '趋势参考，不是诊断。数据来自你授权的设备。',
                    style: type.caption.copyWith(color: colors.ink2),
                  ),
                  const SizedBox(height: 18),
                  const _HealthSection(
                    title: '睡眠',
                    emptyHint: '连接手环后，这里会显示睡眠趋势',
                  ),
                  const SizedBox(height: 12),
                  const _HealthSection(
                    title: '心率',
                    emptyHint: '连接手环后，这里会显示静息心率',
                  ),
                  const SizedBox(height: 12),
                  const _HealthSection(
                    title: '活动',
                    emptyHint: '连接手环后，这里会显示步数与活动',
                  ),
                  const SizedBox(height: 12),
                  const _HealthSection(
                    title: '状态解读',
                    emptyHint: '有数据后，亚丝娜会给出温和的状态解读',
                  ),
                  const SizedBox(height: 18),
                  FilledButton.tonal(
                    onPressed: () => context.go('/health/consent'),
                    child: const Text('健康数据授权'),
                  ),
                ],
              ),
            ),
            // 常驻免责：任意滚动位置均可见（红线 8 / APP-024 AC2）
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(18, 10, 18, 12),
              decoration: BoxDecoration(
                color: colors.surface,
                border: Border(top: BorderSide(color: colors.line)),
              ),
              child: Text(
                disclaimer,
                textAlign: TextAlign.center,
                style: type.caption.copyWith(color: colors.ink3),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _HealthSection extends StatelessWidget {
  const _HealthSection({required this.title, required this.emptyHint});

  final String title;
  final String emptyHint;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: type.sectionTitle),
          const SizedBox(height: 8),
          Text(emptyHint, style: type.body.copyWith(color: colors.ink2)),
          const SizedBox(height: 10),
          Text(
            HealthPage.disclaimer,
            style: type.caption.copyWith(color: colors.ink3),
          ),
        ],
      ),
    );
  }
}
