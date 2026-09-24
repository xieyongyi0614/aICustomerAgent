import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/features/life/presentation/capture_route.dart';

void main() {
  testWidgets('capture route shows three targets and reclassify', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(body: CaptureRouteSheet(initialText: '午饭 35 元')),
      ),
    );
    await tester.pump();
    expect(find.text('记账'), findsOneWidget);
    expect(find.text('任务'), findsOneWidget);
    expect(find.text('备忘录'), findsOneWidget);
    await tester.tap(find.text('记账'));
    await tester.pump();
    expect(find.textContaining('已归到「记账」'), findsOneWidget);
    expect(find.text('改归'), findsOneWidget);
    await tester.tap(find.text('改归'));
    await tester.pump();
    expect(find.text('任务'), findsOneWidget);
  });
}
