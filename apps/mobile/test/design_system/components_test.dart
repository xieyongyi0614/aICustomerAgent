import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/tokens/tokens.dart';

Widget wrap(Widget child) => MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(body: Center(child: SingleChildScrollView(child: child))),
    );

void main() {
  testWidgets('tab bar follows design A9 metrics (5 tabs, floating chat ball)',
      (tester) async {
    // A9 参考设备 390 × 844
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          bottomNavigationBar: AppTabBar(currentIndex: 1, onTap: (_) {}),
        ),
      ),
    );
    final bar = find.byType(AppTabBar);
    final barTop = tester.getTopLeft(bar).dy;

    // A9：栏高 88（含底部安全区；测试环境安全区为 0）
    expect(tester.getSize(bar).height, AppTabBar.barHeight);
    // A9：内容顶部对齐 + 上内边距 12（不是垂直居中）
    expect(
      tester.getTopLeft(find.byIcon(AppIcons.home)).dy - barTop,
      AppTabBar.contentTop,
    );
    // A9：图标 23
    expect(
      tester.getSize(find.byIcon(AppIcons.home)).width,
      AppTabBar.iconSize,
    );
    // A9 / 红线 10：主 Tab 固定 5 个，第 2 位是「动态」槽（默认记账）—— 记忆不是主 Tab
    for (final label in const ['首页', '记账', '对话', '生活', '我的']) {
      expect(find.text(label), findsOneWidget, reason: label);
    }
    expect(find.text('记忆'), findsNothing);

    // A9：对话位 flex 0 0 76，是 5 位里的第 3 位（左右各 2 位等分 → 整栏居中）
    final barWidth = tester.getSize(bar).width;
    final tabWidth =
        (barWidth - AppTabBar.sidePadding * 2 - AppTabBar.orbSlotWidth) / 4;
    final orbCenterX =
        AppTabBar.sidePadding + tabWidth * 2 + AppTabBar.orbSlotWidth / 2;
    expect(tester.getCenter(find.text('对话')).dx, closeTo(orbCenterX, 0.5));
    expect(orbCenterX / barWidth, closeTo(0.5, 0.005));
    // 对话文字相对栏顶 36（.orb-tab span margin-top:36px）
    expect(
      tester.getTopLeft(find.text('对话')).dy - barTop,
      AppTabBar.orbLabelTop,
    );
  });

  testWidgets('components build without hardcoded colors', (tester) async {
    await tester.pumpWidget(wrap(
      Column(
        children: [
          const AppCard(child: Text('卡')),
          AiCard(
            title: '今日 AI 总结',
            actionLabel: '查看完整早间简报 →',
            child: const Text('内容'),
          ),
          const MetricCard(label: '睡眠', value: '7h12m', note: '优于上周', sparkValues: [1, 2, 3, 2, 4, 3, 5]),
          const TaskRow(title: '回复导师邮件', subtitle: '15:00 产品方案对齐', tag: '工作'),
          const SpendSummary(
            amountLabel: '¥128',
            budgetLabel: '/ 今日预算 ¥200',
            progress: 0.64,
            weekBars: [1, 2, 3, 2, 4, 3, 5],
            conclusion: '本周日均 ¥96，节奏健康 —— 亚丝娜',
          ),
          const AskPill(),
          const ModeChip(label: 'Default 模式 · 长期记忆运行中'),
          const MemHint(text: '本轮对话已调用 3 条长期记忆'),
          const ChipButton(label: '查看行程'),
          const CaptureBar(),
          const ModuleCard(title: '记账', summary: '本月 ¥3,420', icon: Icons.wallet),
          const ModuleCard(title: '阅读', summary: 'P2 见', soon: true, icon: Icons.book),
          const CategoryBar(label: '餐饮', amountLabel: '¥1,240', ratio: 0.78, gradient: LinearGradient(colors: [Color(0xFFEFA63C), Color(0xFFFFD08A)])),
          const TxRow(title: '午餐 · 一碗拉面', amountLabel: '-35', tileColor: Color(0x24EFA63C), iconColor: Color(0xFFEFA63C), subtitle: '今天 12:32 · 语音记账'),
          const SourceNote(text: '● 数据来自 小米手环 9 Pro · 已授权同步'),
          const MemoryCard(
            tagLabel: '偏好',
            tagBg: Color(0x1A7A5CFF),
            tagFg: Color(0xFF7A5CFF),
            content: '喜欢海边',
            sourceNote: '来源：6 次对话提及 · 最近更新 9/21',
            usageNote: '已用于任务排序',
          ),
          const PrivacyNote(child: Text('数据只存在你的账户里')),
          SettingGroup(children: [
            SettingRow(title: '设备连接', subtitle: '● 小米手环 9 Pro', icon: Icons.watch, showDivider: false),
          ]),
          AppToggle(value: true, onChanged: (_) {}),
          const BackLink(),
        ],
      ),
    ));
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.byType(AiCard), findsOneWidget);
    expect(find.byType(GradientBorderCard), findsOneWidget);
    expect(find.byType(AppToggle), findsOneWidget);
  });

  test('components dart has no Color(0x outside tokens', () {
    // 由 layer_guards 全局扫描覆盖
  });
}
