import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/rows.dart';
import '../../../design_system/orb/orb.dart';

/// B9 #briefing：深色全屏，早间/晚间共用布局，按 form 切换文案与卡片。
class BriefingPage extends StatelessWidget {
  const BriefingPage({super.key, this.form = 'morning'});

  /// morning | evening
  final String form;

  bool get isEvening => form == 'evening';

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final cards = isEvening ? _eveningCards() : _morningCards();
    return Scaffold(
      body: DecoratedBox(
        decoration: BoxDecoration(gradient: context.gradients.deepBrief),
        child: SafeArea(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(18, 8, 18, 32),
            children: [
              BackLink(
                label: '‹ 返回首页',
                onDark: true,
                onTap: () => Navigator.of(context).maybePop(),
              ),
              Text(
                isEvening ? '晚间总结' : '早间简报',
                style: type.caption.copyWith(color: colors.onDeepTertiary),
              ),
              const SizedBox(height: 8),
              Text(
                isEvening ? '今天辛苦了' : '早上好，今天交给我吧',
                style: type.briefTitle.copyWith(color: colors.onDeepPrimary),
              ),
              const SizedBox(height: 18),
              const Center(child: Orb(size: OrbSize.md)),
              const SizedBox(height: 12),
              Text(
                isEvening
                    ? '明天的节奏我已经帮你排好了'
                    : '天气转凉，记得加件外套',
                textAlign: TextAlign.center,
                style: type.body.copyWith(color: colors.onDeepSecondary),
              ),
              const SizedBox(height: 20),
              for (final c in cards) ...[
                _BriefCard(title: c.$1, body: c.$2, note: c.$3),
                const SizedBox(height: 12),
              ],
              const SizedBox(height: 8),
              Center(
                child: GestureDetector(
                  onTap: () => Navigator.of(context).maybePop(),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        vertical: 12, horizontal: 28),
                    decoration: BoxDecoration(
                      color: colors.surface,
                      borderRadius: context.radii.rFull,
                    ),
                    child: Text(
                      isEvening ? '安顿明天' : '开始今天',
                      style: type.rowTitle.copyWith(color: colors.onWhitePill),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  List<(String, String, String)> _morningCards() => const [
        ('天气', '18° 多云 · 傍晚有风', '出门带件薄外套'),
        ('日程', '15:00 产品方案对齐', '14:30 我会提醒你'),
        ('任务', '3 项 · 已按你的节奏排好', '先回导师邮件，压力小一点'),
        ('生活节奏', '昨晚睡了 7h12m', '上午适合处理需要专注的事'),
      ];

  List<(String, String, String)> _eveningCards() => const [
        ('今天完成', '回复了导师邮件 · 记了 2 笔账', '节奏挺稳的'),
        ('未完成', '产品方案对齐材料', '我帮你挪到明天上午，不用赶'),
        ('生活节奏', '今天走了 6,234 步', '比昨天多一点，继续保持'),
        ('记住的你', '咖啡不加糖 · 十一想去海边', '都记下了，随时可改'),
      ];
}

class _BriefCard extends StatelessWidget {
  const _BriefCard({
    required this.title,
    required this.body,
    required this.note,
  });

  final String title;
  final String body;
  final String note;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 15, horizontal: 16),
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: 0.08),
        borderRadius: context.radii.rMd,
        border: Border.all(color: colors.onDeepSecondary.withValues(alpha: 0.12)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: type.label
                  .copyWith(color: colors.onDeepTertiary, fontSize: 11.5)),
          const SizedBox(height: 6),
          Text(body,
              style: type.rowTitle
                  .copyWith(color: colors.onDeepPrimary, height: 1.5)),
          const SizedBox(height: 4),
          Text(note,
              style: type.caption
                  .copyWith(color: colors.onDeepSecondary, fontSize: 11)),
        ],
      ),
    );
  }
}
