import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/car/data/car_repository.dart';
import 'package:mobile/features/car/domain/car_models.dart';
import 'package:mobile/features/car/presentation/car_page.dart';

class _FakeCarRepository extends CarRepository {
  _FakeCarRepository({this.overview, this.failOverview = false})
      : super(dio: Dio());

  CarOverviewData? overview;
  bool failOverview;
  int overviewCalls = 0;

  @override
  Future<CarOverviewData> fetchOverview() async {
    overviewCalls++;
    if (failOverview) throw Exception('overview down');
    return overview!;
  }

  @override
  Future<CarProfileData> fetchProfile() async => const CarProfileData(
        files: [],
        services: [],
        reminders: [],
      );
}

CarOverviewData _overview({
  CarLoanData? loan = const CarLoanData(
    remainingText: '69300.00',
    monthlyText: '3850.00',
    paidPeriods: 18,
    totalPeriods: 36,
    paidRatio: 0.5,
    badgeText: '2026-10-05T00:00:00',
    settledNote: '2028-09-01T00:00:00',
  ),
  List<String> degraded = const [],
  String? restrictionGuide = '还没配置限行城市、尾号与限行日，配置后我会提前提醒',
  double? chargeKwhMonth,
  double? kwhPer100km,
  List<CarReminderData> reminders = const [
    CarReminderData(
      kind: 'service',
      title: '下次保养',
      detail: '还剩 2,520 km',
      level: 'soon',
    ),
    CarReminderData(
      kind: 'insurance',
      title: '车辆保险',
      detail: '2026-11-01 到期，该比价续保了',
      level: 'soon',
    ),
  ],
}) =>
    CarOverviewData(
      profile: const CarProfileSummary(
        model: '比亚迪 汉 EV',
        plate: '沪 A·D8F2K',
        odometerKm: 12480,
      ),
      loan: loan,
      evMetrics: CarEvMetricsData(
        odometerKm: 12480,
        odometerDeltaMonth: 320,
        chargeCostMinorMonth: 4200,
        chargeCostTextMonth: '42.00',
        chargeCountMonth: 1,
        chargeKwhMonth: chargeKwhMonth,
        kwhPer100km: kwhPer100km,
        basis: 'approximate',
        note: '充电度数本期未结构化存储，电耗精算列 V2（当前按充电费用近似）',
      ),
      expenseBreakdown: const [
        CarExpenseLineData(
          categoryName: '保养',
          netMinor: 20000,
          netText: '200.00',
          count: 1,
        ),
        CarExpenseLineData(
          categoryName: '充电',
          netMinor: 4200,
          netText: '42.00',
          count: 1,
        ),
      ],
      expenseTotalMinor: 24200,
      expenseTotalText: '242.00',
      reminders: reminders,
      restrictionGuide: restrictionGuide,
      recentRecords: const [
        CarRecentRecordData(
          kind: 'service',
          title: '小保养 · 机油机滤',
          subtitle: '华迪 4S 店',
          netMinor: 20000,
          occurredAt: '2026-09-29T09:00:00',
          source: 'manual',
        ),
        CarRecentRecordData(
          kind: 'mileage',
          title: '里程',
          subtitle: '通勤往返',
          odometerDeltaKm: 38,
          occurredAt: '2026-09-28T09:00:00',
          source: 'car',
        ),
      ],
      degradedBlocks: degraded,
    );

Widget _host(Widget child) => MaterialApp(
      theme: buildAppTheme(),
      home: child,
    );

void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 2000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _pumpPage(WidgetTester tester, _FakeCarRepository repo) async {
  _useTallSurface(tester);
  await tester.pumpWidget(_host(CarPage(repository: repo)));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  testWidgets('test_car_page_renders_all_sections', (tester) async {
    final repo = _FakeCarRepository(overview: _overview());
    await _pumpPage(tester, repo);

    expect(find.text('亚丝娜的观察'), findsOneWidget);
    expect(find.text('电车状态'), findsOneWidget);
    expect(find.text('本月养车支出'), findsOneWidget);
    expect(find.text('车辆提醒'), findsOneWidget);
    expect(find.text('最近记录'), findsOneWidget);
    expect(find.text('合计 ¥242.00'), findsOneWidget);
    expect(find.byType(LoanCard), findsOneWidget);
    expect(find.byType(CategoryBar), findsNWidgets(2));
    expect(find.text('本月充电费用 元'), findsOneWidget);
    expect(find.text('42'), findsOneWidget);
    expect(find.text('¥42.00'), findsOneWidget);
  });

  testWidgets('test_car_page_metrics_use_kwh_when_structured',
      (tester) async {
    final repo = _FakeCarRepository(
      overview: _overview(chargeKwhMonth: 186, kwhPer100km: 14.2),
    );
    await _pumpPage(tester, repo);

    expect(find.text('本月充电'), findsOneWidget);
    expect(find.text('186'), findsOneWidget);
    expect(find.text('百公里电耗'), findsOneWidget);
    expect(find.text('14.2'), findsOneWidget);
    expect(find.text('总里程'), findsOneWidget);
    expect(find.text('12,480'), findsOneWidget);
    expect(find.text('本月 +320 km'), findsOneWidget);
  });

  testWidgets('test_car_page_loan_card_absent_when_no_loan', (tester) async {
    final repo = _FakeCarRepository(overview: _overview(loan: null));
    await _pumpPage(tester, repo);

    expect(find.byType(LoanCard), findsNothing);
    expect(find.text('电车状态'), findsOneWidget);
  });

  testWidgets('test_car_page_mileage_row_renders_km_not_amount',
      (tester) async {
    final repo = _FakeCarRepository(overview: _overview());
    await _pumpPage(tester, repo);

    expect(find.text('38 km'), findsOneWidget);
    expect(find.text('里程'), findsOneWidget);
    expect(find.text('-0.00'), findsNothing);
  });

  testWidgets('test_car_page_restriction_absent_when_unconfigured',
      (tester) async {
    final repo = _FakeCarRepository(overview: _overview());
    await _pumpPage(tester, repo);

    final rendered = tester
        .widgetList<Text>(find.byType(Text))
        .map((widget) => widget.data ?? '')
        .join('|');
    expect(find.text('限行提醒'), findsNothing);
    expect(RegExp(r'尾号\s*\d').hasMatch(rendered), isFalse);
    expect(rendered.contains('还没配置限行城市、尾号与限行日'), isTrue);
  });

  testWidgets('test_car_page_degrades_block_without_crash', (tester) async {
    final repo = _FakeCarRepository(
      overview: _overview(degraded: ['expense_breakdown']),
    );
    await _pumpPage(tester, repo);

    expect(find.text('暂时取不到'), findsOneWidget);
    expect(find.text('支出构成暂时取不到，下拉可重试'), findsOneWidget);
    expect(find.byType(CategoryBar), findsNothing);
    expect(find.text('最近记录'), findsOneWidget);
  });

  testWidgets('test_car_page_reloads_after_returning_from_add',
      (tester) async {
    _useTallSurface(tester);
    final repo = _FakeCarRepository(overview: _overview());
    final router = GoRouter(
      initialLocation: '/car',
      routes: [
        GoRoute(path: '/car', builder: (_, _) => CarPage(repository: repo)),
        GoRoute(
          path: '/car/add',
          builder: (context, _) => Scaffold(
            body: Center(
              child: TextButton(
                onPressed: () => context.pop(true),
                child: const Text('back'),
              ),
            ),
          ),
        ),
      ],
    );
    await tester.pumpWidget(
      MaterialApp.router(routerConfig: router, theme: buildAppTheme()),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(repo.overviewCalls, 1);

    await tester.tap(find.text('＋ 记一笔养车费用'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('back'));
    await tester.pumpAndSettle();

    expect(repo.overviewCalls, 2);
  });

  testWidgets('test_car_page_error_state_retries', (tester) async {
    final repo = _FakeCarRepository(overview: _overview(), failOverview: true);
    await _pumpPage(tester, repo);

    expect(find.text(StateCopy.serverError), findsOneWidget);

    repo.failOverview = false;
    await tester.tap(find.text(StateCopy.retryAction));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('电车状态'), findsOneWidget);
    expect(repo.overviewCalls, 2);
  });

  test('test_car_pages_never_import_ledger_or_dio_in_presentation', () {
    const files = [
      'lib/features/car/presentation/car_page.dart',
      'lib/features/car/presentation/car_add_page.dart',
      'lib/features/car/presentation/car_profile_page.dart',
    ];
    for (final path in files) {
      final content = File(path).readAsStringSync();
      expect(content.contains('features/ledger'), isFalse, reason: path);
      expect(content.contains('package:dio'), isFalse, reason: path);
    }
  });

  testWidgets('test_car_page_golden', (tester) async {
    final repo = _FakeCarRepository(overview: _overview());
    await _pumpPage(tester, repo);
    await expectLater(
      find.byType(Scaffold).first,
      matchesGoldenFile('goldens/car_page.png'),
    );
  });
}
