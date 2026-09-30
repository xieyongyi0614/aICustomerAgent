import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/ledger/data/ledger_repository.dart';
import 'package:mobile/features/ledger/presentation/ledger_page.dart';

const _summary = LedgerSummaryData(
  periodLabel: '2026年9月',
  expenseText: '128.50',
  incomeText: '0.00',
  netText: '-128.50',
  entryCount: 2,
  byCategory: [
    LedgerCategoryTotal(categoryId: '餐饮', expenseMinor: 12850, incomeMinor: 0),
  ],
  comparisonLabel: '比上月同期少 12%',
);

const _entries = [
  LedgerEntryData(
    id: 'e-1',
    amountText: '35.00',
    direction: 'expense',
    occurredAt: '今天 12:32',
    merchant: '一碗拉面',
  ),
];

class _FakeLedgerRepository extends LedgerRepository {
  _FakeLedgerRepository({this.autoCount = 0, this.autoFails = false})
    : super(dio: Dio());

  final int autoCount;
  final bool autoFails;

  int summaryCalls = 0;
  int entriesCalls = 0;
  int autoCalls = 0;

  @override
  Future<LedgerSummaryData> fetchSummary({String period = 'month'}) async {
    summaryCalls++;
    return _summary;
  }

  @override
  Future<List<LedgerEntryData>> fetchEntries({int limit = 20}) async {
    entriesCalls++;
    return _entries;
  }

  @override
  Future<LedgerAutoSummaryData> fetchAutoSummary() async {
    autoCalls++;
    if (autoFails) throw Exception('auto-summary down');
    return LedgerAutoSummaryData(
      periodLabel: 'month',
      autoCount: autoCount,
      pendingCount: 0,
    );
  }
}

void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 1500);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

GoRouter _router(LedgerRepository repo) => GoRouter(
  initialLocation: '/ledger',
  routes: [
    GoRoute(
      path: '/ledger',
      builder: (_, _) => LedgerPage(repository: repo),
    ),
    GoRoute(
      path: '/ledger/add',
      builder: (context, _) => Scaffold(
        body: Center(
          child: TextButton(
            onPressed: () => context.pop(true),
            child: const Text('SAVE'),
          ),
        ),
      ),
    ),
    GoRoute(
      path: '/ledger/auto',
      builder: (_, _) => const Scaffold(
        body: Center(child: Text('AUTO')),
      ),
    ),
  ],
);

Future<void> _openLedger(WidgetTester tester, LedgerRepository repo) async {
  _useTallSurface(tester);
  await tester.pumpWidget(
    MaterialApp.router(routerConfig: _router(repo), theme: buildAppTheme()),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

double _topOf(WidgetTester tester, Finder finder) =>
    tester.getTopLeft(finder).dy;

void main() {
  testWidgets(
      'test_ledger_page_entry_row_sits_between_ai_card_and_category_section',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository());
    expect(_topOf(tester, find.byType(AiCard)), lessThan(_topOf(tester, find.byType(EntryCard).first)));
    expect(
      _topOf(tester, find.byType(EntryCard).first),
      lessThan(_topOf(tester, find.text('分类支出'))),
    );
    expect(
      _topOf(tester, find.text('分类支出')),
      lessThan(_topOf(tester, find.text('最近账单'))),
    );
    expect(find.byType(EntryCard), findsNWidgets(2));
  });

  testWidgets('test_ledger_page_entry_row_left_goes_to_ledger_add',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository());
    await tester.tap(find.text('手动记一笔'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('SAVE'), findsOneWidget);
  });

  testWidgets('test_ledger_page_entry_row_right_goes_to_ledger_auto',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository());
    await tester.tap(find.text('AI 自动记账'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('AUTO'), findsOneWidget);
  });

  testWidgets('test_ledger_page_reloads_after_returning_from_add',
      (tester) async {
    final repo = _FakeLedgerRepository();
    await _openLedger(tester, repo);
    expect(repo.summaryCalls, 1);
    expect(repo.entriesCalls, 1);
    await tester.tap(find.text('手动记一笔'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text('SAVE'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(repo.summaryCalls, 2);
    expect(repo.entriesCalls, 2);
  });

  testWidgets('test_ledger_page_entry_subtitle_uses_real_auto_count',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository(autoCount: 12));
    expect(find.text('本月已自动记 12 笔'), findsOneWidget);
    expect(find.textContaining('42'), findsNothing);
  });

  testWidgets('test_ledger_page_entry_subtitle_is_honest_when_zero',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository(autoCount: 0));
    expect(find.text('本月还没有自动记账'), findsOneWidget);
    expect(find.textContaining('已自动记'), findsNothing);
  });

  testWidgets('test_ledger_page_entry_subtitle_degrades_on_failure',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository(autoFails: true));
    expect(find.text('看看 AI 记了什么'), findsOneWidget);
    expect(find.byType(EntryCard), findsNWidgets(2));
    expect(tester.takeException(), isNull);
  });

  testWidgets('test_ledger_page_existing_sections_unchanged', (tester) async {
    await _openLedger(tester, _FakeLedgerRepository());
    expect(find.text('¥128.50'), findsOneWidget);
    expect(find.text('本期共 2 笔。收入 0.00，结余 -128.50。'), findsOneWidget);
    expect(find.text('比上月同期少 12%'), findsOneWidget);
    expect(find.byType(CategoryBar), findsOneWidget);
    expect(find.byType(TxRow), findsOneWidget);
    expect(find.text('-35.00'), findsOneWidget);
  });

  testWidgets('test_ledger_page_entry_row_golden', (tester) async {
    await _openLedger(tester, _FakeLedgerRepository(autoCount: 12));
    await expectLater(
      find.byType(Scaffold),
      matchesGoldenFile('goldens/ledger_page_entry_row.png'),
    );
  });

  test('test_ledger_page_never_imports_dio', () {
    final source = File('lib/features/ledger/presentation/ledger_page.dart')
        .readAsStringSync();
    expect(source.contains('package:dio'), isFalse);
  });
}
