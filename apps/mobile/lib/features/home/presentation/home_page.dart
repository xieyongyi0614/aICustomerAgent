import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';

/// B1 #home 十一段：先结论 → 后数据 → 再行动。
/// 三宫格双分支：真实数据 / 空态引导授权（不得假数据）。
class HomePage extends StatelessWidget {
  const HomePage({super.key, this.healthAuthorized = false});

  /// PLT-001 未通过前默认走空态分支
  final bool healthAuthorized;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: context.spacing.screenPadding,
          children: [
            const _GreetingRow(),
            const SizedBox(height: 18),
            const _HeroBlock(),
            const SizedBox(height: 20),
            // 3 AI 结论卡（视觉焦点，先于数据）
            AiCard(
              title: '今日 AI 总结',
              actionLabel: '查看完整早间简报 →',
              onAction: () {},
              child: Text(
                '昨晚睡得不错，上午适合处理需要专注的事。午餐后记得留 20 分钟散步。',
                style: context.typography.body.copyWith(
                  color: colors.bodyOnCard,
                  height: 1.65,
                ),
              ),
            ),
            const SizedBox(height: 24),
            _SectionTitle(title: '今日状态', hint: healthAuthorized ? '来自小米手环 9 Pro' : null),
            const SizedBox(height: 10),
            if (healthAuthorized)
              const _HealthGrid()
            else
              const _HealthAuthEmpty(),
            const SizedBox(height: 24),
            const _SectionTitle(title: '今日任务', hint: '3 项 · AI 已排序'),
            const SizedBox(height: 6),
            const AppCard(
              listPadding: true,
              child: Column(
                children: [
                  TaskRow(title: '回复导师邮件', tag: '工作', done: true, showDivider: true),
                  TaskRow(
                    title: '15:00 产品方案对齐',
                    subtitle: '14:30 提醒',
                    tag: '工作',
                    showDivider: true,
                  ),
                  TaskRow(title: '给妈妈回电话', tag: '晚间', showDivider: false),
                ],
              ),
            ),
            const SizedBox(height: 24),
            _SectionTitle(
              title: '今日消费',
              trailingAction: '查看账本 ›',
              onTrailing: () {},
            ),
            const SizedBox(height: 10),
            SpendSummary(
              amountLabel: '¥128',
              budgetLabel: '/ 今日预算 ¥200',
              progress: 0.64,
              weekBars: [80, 120, 90, 140, 100, 70, 128],
              conclusion: '本周日均 ¥96，节奏健康 —— 亚丝娜',
            ),
            const SizedBox(height: 20),
            AskPill(onSend: () {}),
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }
}

class _GreetingRow extends StatelessWidget {
  const _GreetingRow();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('今天 · 周二',
                  style: type.caption.copyWith(color: colors.ink2)),
              Text('早上好', style: type.heroTitle.copyWith(fontSize: 17)),
            ],
          ),
        ),
        Container(
          width: 38,
          height: 38,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: context.gradients.avatar,
          ),
          child: Icon(Icons.person, size: 20, color: colors.avatarText),
        ),
      ],
    );
  }
}

class _HeroBlock extends StatelessWidget {
  const _HeroBlock();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Column(
      children: [
        const Center(child: Orb(size: OrbSize.lg)),
        const SizedBox(height: 12),
        Text('今天也交给我吧',
            textAlign: TextAlign.center, style: type.heroTitle),
        const SizedBox(height: 6),
        Text('亚丝娜已为你整理好今天的一切',
            textAlign: TextAlign.center,
            style: type.body.copyWith(color: colors.ink2, fontSize: 13.5)),
        const SizedBox(height: 10),
        const Center(
          child: ModeChip(label: 'Default 模式 · 长期记忆运行中'),
        ),
      ],
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({
    required this.title,
    this.hint,
    this.trailingAction,
    this.onTrailing,
  });

  final String title;
  final String? hint;
  final String? trailingAction;
  final VoidCallback? onTrailing;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      children: [
        Text(title, style: type.sectionTitle),
        const Spacer(),
        if (hint != null)
          Text(hint!, style: type.caption.copyWith(color: colors.ink3)),
        if (trailingAction != null)
          GestureDetector(
            onTap: onTrailing,
            child: Text(trailingAction!,
                style: type.caption.copyWith(color: colors.aiPrimary)),
          ),
      ],
    );
  }
}

class _HealthGrid extends StatelessWidget {
  const _HealthGrid();

  @override
  Widget build(BuildContext context) {
    return const Row(
      children: [
        Expanded(
          child: MetricCard(label: '睡眠', value: '7h12m', note: '优于上周'),
        ),
        SizedBox(width: 10),
        Expanded(
          child: MetricCard(label: '静息心率', value: '62', unit: 'bpm', note: '平稳'),
        ),
        SizedBox(width: 10),
        Expanded(
          child: MetricCard(label: '步数', value: '6,234', note: '目标 8,000'),
        ),
      ],
    );
  }
}

/// 空态 + 引导授权：零数值、零留白（决策 D1）。
class _HealthAuthEmpty extends StatelessWidget {
  const _HealthAuthEmpty();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return AppCard(
      child: Column(
        children: [
          Text('还没有健康数据',
              style: type.rowTitle.copyWith(color: colors.ink)),
          const SizedBox(height: 8),
          Text(
            '连接手环后，这里会显示睡眠、心率和步数',
            textAlign: TextAlign.center,
            style: type.body.copyWith(color: colors.ink2),
          ),
          const SizedBox(height: 14),
          ChipButton(label: '去授权健康数据', onTap: () {}),
        ],
      ),
    );
  }
}
