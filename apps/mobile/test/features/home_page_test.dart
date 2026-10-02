import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/home/data/home_repository.dart';
import 'package:mobile/features/home/presentation/home_page.dart';

HomeSummaryData _summary({
  bool healthAuthorized = false,
  List<HomeHealthMetric> metrics = const [],
}) => HomeSummaryData(
      dateLabel: '今天',
      greeting: '早上好',
      headline: '今天也交给我吧',
      sub: '亚丝娜已为你整理好今天的一切',
      modeChip: 'Default 模式',
      insightTitle: '今日 AI 总结',
      insightNarrative: '上午适合专注。',
      insightAction: '查看完整早间简报 →',
      healthAuthorized: healthAuthorized,
      healthEmptyHint: '连接手环后，这里会显示睡眠、心率和步数',
      healthMetrics: metrics,
      tasks: const [],
      tasksHint: '0 项',
      spend: const HomeSpend(
        amountLabel: '¥0',
        budgetLabel: '/ 今日预算 ¥200',
        progress: 0,
        conclusion: '今天还没有记账 —— 亚丝娜',
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
    final status = find.text('今日状态');
    expect(ai, findsOneWidget);
    expect(status, findsOneWidget);
    expect(tester.getTopLeft(ai).dy, lessThan(tester.getTopLeft(status).dy));
  });

  testWidgets('health empty branch has no fake numbers', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: HomePage(debugSummary: _summary()),
      ),
    );
    await tester.pump();
    expect(find.text('还没有健康数据'), findsOneWidget);
    expect(find.text('7h12m'), findsNothing);
    expect(find.text('去授权健康数据'), findsOneWidget);
  });

  testWidgets('health data branch renders only API-provided metrics', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: HomePage(
          healthAuthorized: true,
          debugSummary: _summary(
            healthAuthorized: true,
            metrics: const [
              HomeHealthMetric(label: '睡眠', value: '7h12m', note: '来自 Health Connect'),
            ],
          ),
        ),
      ),
    );
    await tester.pump();
    expect(find.text('7h12m'), findsOneWidget);
    expect(find.text('还没有健康数据'), findsNothing);
  });

  testWidgets('authorized without synced metrics shows honest empty state', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: HomePage(
          healthAuthorized: true,
          debugSummary: _summary(healthAuthorized: true),
        ),
      ),
    );
    await tester.pump();
    expect(find.text('已连接设备，今天的健康数据还没同步过来'), findsOneWidget);
    expect(find.text('7h12m'), findsNothing);
    expect(find.text('62'), findsNothing);
    expect(find.text('6,234'), findsNothing);
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
      healthAuthorized: false,
      tasks: const [],
      tasksHint: '',
      spend: const HomeSpend(
        amountLabel: '¥96',
        budgetLabel: '/ 今日预算 ¥200',
        progress: 0.48,
        conclusion: '本周日均 ¥96，节奏健康 —— 亚丝娜',
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
