import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/features/home/data/home_repository.dart';
import 'package:mobile/features/home/presentation/home_page.dart';

HomeSummaryData _summary({bool healthAuthorized = false}) => HomeSummaryData(
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

  testWidgets('health data branch when authorized', (tester) async {
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
    expect(find.text('7h12m'), findsOneWidget);
    expect(find.text('还没有健康数据'), findsNothing);
  });
}
