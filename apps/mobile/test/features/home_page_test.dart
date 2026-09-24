import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/features/home/presentation/home_page.dart';

void main() {
  testWidgets('home renders AI summary before data sections', (tester) async {
    await tester.pumpWidget(
      MaterialApp(theme: buildAppTheme(), home: const HomePage()),
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
      MaterialApp(theme: buildAppTheme(), home: const HomePage()),
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
        home: const HomePage(healthAuthorized: true),
      ),
    );
    await tester.pump();
    expect(find.text('7h12m'), findsOneWidget);
    expect(find.text('还没有健康数据'), findsNothing);
  });
}
