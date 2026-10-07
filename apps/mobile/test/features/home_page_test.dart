import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/home/data/home_repository.dart';
import 'package:mobile/features/home/presentation/home_page.dart';

HomeSummaryData _summary() => const HomeSummaryData(
      dateLabel: '今天',
      greeting: '早上好',
      headline: '今天也交给我吧',
      sub: '亚丝娜已为你整理好今天的一切',
      modeChip: 'Default 模式',
      insightTitle: '今日 AI 总结',
      insightNarrative: '上午适合专注。',
      insightAction: '查看完整早间简报 →',
      tasks: [],
      tasksHint: '0 项',
      spend: HomeSpend(
        amountLabel: '¥0',
        noteLabel: '近 7 天',
        conclusion: '最近还没有记账 —— 亚丝娜',
      ),
    );

void main() {
  testWidgets('home renders AI summary before data sections', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: HomePage(debugSummary: _summary()),
      ),
    );
    await tester.pump();
    final ai = find.text('今日 AI 总结');
    final tasks = find.text('今日任务');
    expect(ai, findsOneWidget);
    expect(tasks, findsOneWidget);
    expect(tester.getTopLeft(ai).dy, lessThan(tester.getTopLeft(tasks).dy));
  });

  testWidgets('home spend section is weekly and drops the fake budget',
      (tester) async {
    tester.view.physicalSize = const Size(390, 1800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: HomePage(debugSummary: _summary()),
      ),
    );
    await tester.pump();

    expect(find.text('最近消费'), findsOneWidget);
    expect(find.text('今日消费'), findsNothing, reason: '按日口径太细，已废弃');
    expect(find.text('近 7 天'), findsOneWidget);
    expect(
      tester.widget<SpendSummary>(find.byType(SpendSummary)).progress,
      isNull,
      reason: '没有真实预算数据源时不再撑进度条（旧「今日预算 ¥200」是硬编码）',
    );
  });

  testWidgets('home never renders health section', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: HomePage(debugSummary: _summary()),
      ),
    );
    await tester.pump();
    expect(find.text('今日状态'), findsNothing);
    expect(find.text('还没有健康数据'), findsNothing);
    expect(find.text('去授权健康数据'), findsNothing);
  });

  testWidgets('spend week bars render only when backend provides them',
      (tester) async {
    // 消费区在折叠线下方，拉高测试面让 ListView 实际构建 SpendSummary。
    tester.view.physicalSize = const Size(390, 1800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: HomePage(debugSummary: _summary()),
      ),
    );
    await tester.pump();
    expect(
      tester.widget<SpendSummary>(find.byType(SpendSummary)).weekBars,
      isEmpty,
      reason: '无 week_bars 下发时周柱状图不渲染',
    );

    final withBars = HomeSummaryData(
      dateLabel: '今天',
      greeting: '早上好',
      headline: '今天也交给我吧',
      sub: '',
      modeChip: '',
      insightTitle: '今日 AI 总结',
      insightNarrative: '',
      tasks: const [],
      tasksHint: '',
      spend: const HomeSpend(
        amountLabel: '¥96',
        noteLabel: '近 7 天 · 4 笔',
        progress: 0.48,
        conclusion: '近 7 天日均 ¥96，比上周少 12% —— 亚丝娜',
        weekBars: <double>[12, 30, 8, 0, 45, 22, 96],
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        // UniqueKey 强制重建 State：同型 HomePage 复用 State 时 initState 不重跑。
        home: HomePage(key: UniqueKey(), debugSummary: withBars),
      ),
    );
    await tester.pump();
    expect(
      tester.widget<SpendSummary>(find.byType(SpendSummary)).weekBars,
      <double>[12, 30, 8, 0, 45, 22, 96],
      reason: 'week_bars 下发后透传给周柱状图',
    );
  });
}
