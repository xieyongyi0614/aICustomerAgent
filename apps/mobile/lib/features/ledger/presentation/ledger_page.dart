import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/cards.dart';
import '../../../design_system/components/chips.dart';
import '../../../design_system/components/rows.dart';

/// B5 #ledger 账本：深色总览 + AI 观察 + 分类 + 账单。Tab 隐藏由路由元数据控制。
class LedgerPage extends StatelessWidget {
  const LedgerPage({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final gradients = context.gradients;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: ListView(
          padding: context.spacing.screenPadding.copyWith(bottom: 40),
          children: [
            BackLink(label: '‹ 生活', onTap: () => Navigator.of(context).maybePop()),
            Container(
              padding: const EdgeInsets.all(18),
              decoration: BoxDecoration(
                gradient: gradients.deepSummary,
                borderRadius: context.radii.rLg,
                boxShadow: context.elevation.deep,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('9 月总支出',
                      style: type.caption.copyWith(color: colors.onDeepSecondary)),
                  const SizedBox(height: 6),
                  Text('¥3,420',
                      style: type.numeric(type.display)
                          .copyWith(color: colors.onDeepPrimary)),
                  const SizedBox(height: 6),
                  Container(
                    padding:
                        const EdgeInsets.symmetric(vertical: 3, horizontal: 8),
                    decoration: BoxDecoration(
                      color: colors.health.withValues(alpha: 0.18),
                      borderRadius: context.radii.rFull,
                    ),
                    child: Text('比上月同期少 8%',
                        style: type.caption.copyWith(color: colors.health)),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),
            AiCard(
              title: '亚丝娜的观察',
              child: Text(
                '旅行预算有点紧，可以把旅行基金上调至 ¥650/月，我帮你自动划转。',
                style: type.body.copyWith(color: colors.bodyOnCard, height: 1.65),
              ),
            ),
            const SizedBox(height: 20),
            _SectionTitle(title: '分类支出', hint: '9 月'),
            const SizedBox(height: 10),
            CategoryBar(
              label: '餐饮',
              amountLabel: '¥1,240（78%）',
              ratio: 0.78,
              gradient: gradients.barMoney,
            ),
            CategoryBar(
              label: '交通',
              amountLabel: '¥860（54%）',
              ratio: 0.54,
              gradient: gradients.barBlue,
            ),
            CategoryBar(
              label: '购物',
              amountLabel: '¥720（45%）',
              ratio: 0.45,
              gradient: gradients.barPurple,
            ),
            CategoryBar(
              label: '娱乐',
              amountLabel: '¥600（38%）',
              ratio: 0.38,
              gradient: gradients.barGreen,
            ),
            const SizedBox(height: 14),
            _SectionTitle(title: '最近账单', hint: 'AI 自动分类'),
            const SizedBox(height: 6),
            TxRow(
              title: '午餐 · 一碗拉面',
              amountLabel: '-35',
              tileColor: colors.tileMoney,
              iconColor: colors.money,
              icon: Icons.restaurant,
              subtitle: '今天 12:32 · 语音记账',
            ),
            TxRow(
              title: '地铁出行',
              amountLabel: '-6',
              tileColor: colors.tileInfo,
              iconColor: colors.aiBlue,
              icon: Icons.train,
              subtitle: '今天 08:47 · 自动同步',
            ),
            TxRow(
              title: '咖啡豆 · 手冲拼配',
              amountLabel: '-87',
              tileColor: colors.tileWarm,
              iconColor: colors.warm,
              icon: Icons.coffee,
              subtitle: '昨天 · 「咖啡不加糖」已记忆',
              showDivider: false,
            ),
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
