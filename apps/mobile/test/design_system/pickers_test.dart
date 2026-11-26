import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/tokens/tokens.dart';

Future<void> _openSheet(
  WidgetTester tester,
  Future<void> Function(BuildContext context) open,
) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(
        backgroundColor: AppColors.light.canvas,
        body: Builder(
          builder: (context) => Center(
            child: GestureDetector(
              onTap: () => open(context),
              child: const Text('打开'),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('打开'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('test_choice_sheet_groups_and_returns_value', (tester) async {
    String? picked;
    await _openSheet(tester, (context) async {
      picked = await showChoiceSheet<String>(
        context: context,
        title: '选车型',
        items: const [
          ChoiceSheetItem(
            value: 'byd-han',
            label: '汉 EV',
            group: '比亚迪',
            note: '纯电',
          ),
          ChoiceSheetItem(
            value: 'tsl-m3',
            label: 'Model 3',
            group: '特斯拉',
            note: '纯电',
          ),
        ],
      );
    });

    expect(find.text('选车型'), findsOneWidget);
    expect(find.text('比亚迪'), findsOneWidget);
    expect(find.text('特斯拉'), findsOneWidget);
    expect(find.text('纯电'), findsNWidgets(2));

    await tester.tap(find.text('Model 3'));
    await tester.pumpAndSettle();
    expect(picked, 'tsl-m3');
  });

  testWidgets('test_choice_sheet_search_filters_and_free_text_wins',
      (tester) async {
    String? picked;
    await _openSheet(tester, (context) async {
      picked = await showChoiceSheet<String>(
        context: context,
        title: '选车型',
        searchable: true,
        freeTextBuilder: (query) => query,
        items: const [
          ChoiceSheetItem(value: 'byd-han', label: '汉 EV', group: '比亚迪'),
        ],
      );
    });

    await tester.enterText(find.byKey(pickerSearchKey), '汉 EV 冠军版');
    await tester.pump();
    expect(find.text('用「汉 EV 冠军版」'), findsOneWidget);
    expect(find.text('汉 EV'), findsNothing);

    await tester.tap(find.text('用「汉 EV 冠军版」'));
    await tester.pumpAndSettle();
    expect(picked, '汉 EV 冠军版');
  });

  testWidgets('test_date_wheel_sheet_confirms_initial_date', (tester) async {
    DateTime? picked;
    await _openSheet(tester, (context) async {
      picked = await showDateWheelSheet(
        context: context,
        title: '保险到期',
        initial: DateTime(2027, 1, 15),
      );
    });

    expect(find.byType(WheelColumn), findsNWidgets(3));
    expect(find.text('2027'), findsOneWidget);
    expect(find.text('1 月'), findsOneWidget);
    expect(find.text('15 日'), findsOneWidget);

    await tester.tap(find.text('完成'));
    await tester.pumpAndSettle();
    expect(picked, DateTime(2027, 1, 15));
  });

  testWidgets('test_date_wheel_sheet_cancel_returns_null', (tester) async {
    DateTime? picked = DateTime(2000);
    await _openSheet(tester, (context) async {
      picked = await showDateWheelSheet(
        context: context,
        title: '年检到期',
        initial: DateTime(2027, 4, 1),
      );
    });

    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(picked, isNull);
  });

  testWidgets('test_datetime_wheel_sheet_confirms_initial_moment',
      (tester) async {
    DateTime? picked;
    await _openSheet(tester, (context) async {
      picked = await showDateTimeWheelSheet(
        context: context,
        title: '记账时间',
        initial: DateTime(2026, 10, 3, 8, 5, 7),
      );
    });

    expect(find.byType(WheelColumn), findsNWidgets(6));
    expect(find.text('2026'), findsOneWidget);
    expect(find.text('10 月'), findsOneWidget);
    expect(find.text('3 日'), findsOneWidget);

    await tester.tap(find.text('完成'));
    await tester.pumpAndSettle();
    expect(picked, DateTime(2026, 10, 3, 8, 5, 7));
  });

  testWidgets('test_datetime_wheel_sheet_cancel_returns_null', (tester) async {
    DateTime? picked = DateTime(2000);
    await _openSheet(tester, (context) async {
      picked = await showDateTimeWheelSheet(
        context: context,
        title: '记账时间',
        initial: DateTime(2026, 10, 3, 8, 5),
      );
    });

    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(picked, isNull);
  });

  testWidgets('test_wheel_column_reports_scroll', (tester) async {
    var index = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: Center(
            child: WheelColumn(
              items: const ['1 月', '2 月', '3 月'],
              initialIndex: 0,
              onChanged: (value) => index = value,
            ),
          ),
        ),
      ),
    );

    await tester.drag(find.byType(WheelColumn), const Offset(0, -40));
    await tester.pumpAndSettle();
    expect(index, 1);
  });
}
