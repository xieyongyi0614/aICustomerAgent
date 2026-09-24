import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/chips.dart';

/// B4 #life：捕获条 → 模块 3×2 → soon 占位。
class LifePage extends StatelessWidget {
  const LifePage({super.key});

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
            Text('生活', style: type.pageTitle),
            Text('说一句话，亚丝娜帮你归位',
                style: type.sub.copyWith(color: colors.ink2)),
            const SizedBox(height: 16),
            const CaptureBar(),
            const _SectionTitle(title: '生活模块', hint: 'Skill 化 · 可持续扩展'),
            const SizedBox(height: 10),
            const _ModuleGrid(),
            const SizedBox(height: 24),
            const _SectionTitle(title: '即将上线', hint: 'Skill 商店'),
            const SizedBox(height: 10),
            const _SoonGrid(),
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, this.hint});

  final String title;
  final String? hint;

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
      ],
    );
  }
}

class _ModuleGrid extends StatelessWidget {
  const _ModuleGrid();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: ModuleCard(
                title: '记账',
                summary: '本月节奏稳，餐饮略高',
                icon: Icons.wallet,
                tileBg: colors.tileMoney,
                tileFg: colors.money,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '备忘录',
                summary: '12 条 · AI 已整理',
                icon: Icons.notes,
                tileBg: colors.tileAi,
                tileFg: colors.aiPrimary,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '任务',
                summary: '今天还有 2 项',
                icon: Icons.checklist,
                tileBg: colors.tileHealth,
                tileFg: colors.health,
              ),
            ),
          ],
        ),
        const SizedBox(height: 11),
        Row(
          children: [
            Expanded(
              child: ModuleCard(
                title: '日历',
                summary: '15:00 方案对齐',
                icon: Icons.calendar_month,
                tileBg: colors.tileInfo,
                tileFg: colors.aiBlue,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '旅行',
                summary: '十一行程规划中',
                icon: Icons.flight,
                tileBg: colors.tileTravel,
                tileFg: colors.aiCyan,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '健康',
                summary: '状态良好',
                icon: Icons.favorite,
                tileBg: colors.tileHealth,
                tileFg: colors.health,
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _SoonGrid extends StatelessWidget {
  const _SoonGrid();

  @override
  Widget build(BuildContext context) {
    return const Row(
      children: [
        Expanded(
          child: ModuleCard(
            title: '阅读',
            summary: 'V2 见',
            icon: Icons.menu_book,
            soon: true,
          ),
        ),
        SizedBox(width: 11),
        Expanded(
          child: ModuleCard(
            title: '习惯打卡',
            summary: 'V2 见',
            icon: Icons.repeat,
            soon: true,
          ),
        ),
        SizedBox(width: 11),
        Expanded(
          child: ModuleCard(
            title: '更多 Skill',
            summary: '持续扩展',
            icon: Icons.add_box,
            soon: true,
          ),
        ),
      ],
    );
  }
}
