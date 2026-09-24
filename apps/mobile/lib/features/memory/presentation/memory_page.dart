import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/cards.dart';

/// B6 记忆页：分组 + 来源追溯 + 用途回执 + 隐私承诺。
class MemoryPage extends StatelessWidget {
  const MemoryPage({super.key});

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
            Text('亚丝娜记住的你', style: type.pageTitle),
            Text('每条都能看到来源，也可以随时遗忘',
                style: type.sub.copyWith(color: colors.ink2)),
            const SizedBox(height: 16),
            MemoryCard(
              tagLabel: '偏好',
              tagBg: colors.tagPreferenceBg,
              tagFg: colors.tagPreferenceFg,
              content: '喜欢海边旅行，预算偏紧时选人少的目的地',
              sourceNote: '来源：6 次对话提及 · 最近更新 9/21',
              usageNote: '已用于任务排序',
              onEdit: () {},
              onForget: () {},
            ),
            MemoryCard(
              tagLabel: '习惯',
              tagBg: colors.tagHabitBg,
              tagFg: colors.tagHabitFg,
              content: '咖啡不加糖',
              sourceNote: '来源：2 次对话提及 · 最近更新 9/20',
              usageNote: '已用于账单备注',
              onEdit: () {},
              onForget: () {},
            ),
            MemoryCard(
              tagLabel: '目标',
              tagBg: colors.tagGoalBg,
              tagFg: colors.tagGoalFg,
              content: '十一前完成旅行规划',
              sourceNote: '来源：3 次对话提及 · 最近更新 9/18',
              onEdit: () {},
              onForget: () {},
            ),
            PrivacyNote(
              child: Text(
                '这些记忆只存在你的账户里，用来让我更懂你。你可以随时编辑或遗忘任何一条。',
              ),
            ),
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }
}
