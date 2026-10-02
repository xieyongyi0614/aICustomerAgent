import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/tokens/tokens.dart';
import 'package:mobile/features/ledger/data/ledger_repository.dart';
import 'package:mobile/features/ledger/presentation/ledger_category_visuals.dart';
import 'package:mobile/features/ledger/presentation/ledger_page.dart';

const _summary = LedgerSummaryData(
  periodLabel: '2026年9月',
  expenseText: '128.50',
  incomeText: '0.00',
  netText: '-128.50',
  entryCount: 2,
  byCategory: [
    LedgerCategoryTotal(categoryId: '餐饮', expenseMinor: 12850, incomeMinor: 0),
    LedgerCategoryTotal(categoryId: '交通', expenseMinor: 8600, incomeMinor: 0),
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

LedgerPendingData _pending({
  String key = 'pk-1',
  String reason = 'amount_over_threshold',
  String question = '这笔要怎么记？',
  List<LedgerPendingCandidate> candidates = const [],
  int? amountMinor,
  String? categoryHint,
  String? direction,
  String? merchantHint,
}) => LedgerPendingData(
  pendingKey: key,
  reason: reason,
  question: question,
  candidates: candidates,
  amountMinor: amountMinor,
  categoryHint: categoryHint,
  direction: direction,
  merchantHint: merchantHint,
);

class _FakeLedgerRepository extends LedgerRepository {
  _FakeLedgerRepository({
    this.autoCount = 0,
    this.autoFails = false,
    this.pending = const [],
    this.pendingFails = false,
    this.confirmFails = false,
    this.entries = _entries,
    this.categories = const [],
  }) : super(dio: Dio());

  final int autoCount;
  final bool autoFails;
  final List<LedgerPendingData> pending;
  final bool pendingFails;
  bool confirmFails;
  final List<LedgerEntryData> entries;
  final List<LedgerCategoryData> categories;

  int summaryCalls = 0;
  int entriesCalls = 0;
  int autoCalls = 0;
  int confirmCalls = 0;
  int ignoreCalls = 0;
  final List<String?> confirmedCategories = [];
  final List<String?> confirmedDirections = [];

  @override
  Future<LedgerSummaryData> fetchSummary({String period = 'month'}) async {
    summaryCalls++;
    return _summary;
  }

  @override
  Future<List<LedgerEntryData>> fetchEntries({int limit = 20}) async {
    entriesCalls++;
    return entries;
  }

  @override
  Future<List<LedgerCategoryData>> fetchCategories({String? kind}) async =>
      categories;

  @override
  Future<LedgerAutoSummaryData> fetchAutoSummary() async {
    autoCalls++;
    if (autoFails) throw Exception('auto-summary down');
    return LedgerAutoSummaryData(
      periodLabel: 'month',
      autoCount: autoCount,
      pendingCount: pending.length,
    );
  }

  @override
  Future<List<LedgerPendingData>> fetchPending() async {
    if (pendingFails) throw Exception('pending down');
    return pending;
  }

  @override
  Future<void> confirmPending(
    String pendingKey, {
    String? categoryName,
    String? direction,
    int? amountMinor,
  }) async {
    confirmCalls++;
    confirmedCategories.add(categoryName);
    confirmedDirections.add(direction);
    if (confirmFails) throw Exception('confirm down');
  }

  @override
  Future<void> ignorePending(String pendingKey) async {
    ignoreCalls++;
  }
}

void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 1800);
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
  testWidgets('test_ledger_page_order_follows_design', (tester) async {
    await _openLedger(
      tester,
      _FakeLedgerRepository(pending: [_pending()]),
    );
    expect(
      _topOf(tester, find.byType(AiCard)),
      lessThan(_topOf(tester, find.text('需要你的确认'))),
    );
    expect(
      _topOf(tester, find.text('需要你的确认')),
      lessThan(_topOf(tester, find.byType(EntryCard))),
    );
    expect(
      _topOf(tester, find.byType(EntryCard)),
      lessThan(_topOf(tester, find.text('分类支出'))),
    );
    expect(
      _topOf(tester, find.text('分类支出')),
      lessThan(_topOf(tester, find.text('最近账单'))),
    );
    expect(
      find.byType(EntryCard),
      findsOneWidget,
      reason: 'IA 裁决 2：记账不拆「手动 / AI 自动」两个并列入口',
    );
    expect(find.byType(SyncLink), findsOneWidget);
  });

  testWidgets('test_ledger_page_single_entry_goes_to_ledger_add',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository());
    await tester.tap(find.text('记一笔'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('SAVE'), findsOneWidget);
  });

  testWidgets('test_ledger_page_sync_link_goes_to_ledger_auto',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository(autoCount: 12));
    await tester.tap(find.byType(SyncLink));
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
    await tester.tap(find.text('记一笔'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.tap(find.text('SAVE'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(repo.summaryCalls, 2);
    expect(repo.entriesCalls, 2);
  });

  testWidgets('test_ledger_page_sync_link_uses_real_auto_count',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository(autoCount: 12));
    expect(find.text('本月已自动记 12 笔 · 同步与 AI 规则'), findsOneWidget);
    expect(find.textContaining('42'), findsNothing);
  });

  testWidgets('test_ledger_page_sync_link_is_honest_when_zero', (tester) async {
    await _openLedger(tester, _FakeLedgerRepository(autoCount: 0));
    expect(find.text('本月还没有自动记账 · 同步与 AI 规则'), findsOneWidget);
    expect(find.textContaining('已自动记'), findsNothing);
  });

  testWidgets('test_ledger_page_sync_link_degrades_on_failure', (tester) async {
    await _openLedger(tester, _FakeLedgerRepository(autoFails: true));
    expect(find.text('同步与 AI 规则'), findsOneWidget);
    expect(find.byType(EntryCard), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('test_ledger_page_hides_confirm_block_when_nothing_pending',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository());
    expect(find.text('需要你的确认'), findsNothing);
    expect(find.byType(LedgerConfirmRow), findsNothing);
  });

  testWidgets('test_ledger_page_pending_failure_only_hides_the_block',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository(pendingFails: true));
    expect(find.text('需要你的确认'), findsNothing);
    expect(
      find.text('¥128.50'),
      findsOneWidget,
      reason: '待确认取不到不该把整页打成错误态',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('test_ledger_page_confirm_row_shows_title_and_judgment',
      (tester) async {
    await _openLedger(
      tester,
      _FakeLedgerRepository(
        pending: [
          _pending(
            merchantHint: 'Apple Store',
            amountMinor: 6800,
            categoryHint: '娱乐',
            direction: 'expense',
          ),
        ],
      ),
    );
    expect(find.text('需要你的确认'), findsOneWidget);
    expect(find.text('1 笔 · 确认后我会记住'), findsOneWidget);
    expect(find.text('Apple Store · ¥68.00'), findsOneWidget);
    expect(
      find.text('我的判断：娱乐 · 支出'),
      findsOneWidget,
      reason: 'direction 要转中文，不能把枚举值直接抛给用户',
    );
  });

  testWidgets('test_ledger_page_confirm_actions_follow_reason', (tester) async {
    await _openLedger(
      tester,
      _FakeLedgerRepository(
        pending: [
          _pending(key: 'pk-dir', reason: 'direction_ambiguous'),
          _pending(
            key: 'pk-cat',
            reason: 'category_ambiguous',
            candidates: const [
              LedgerPendingCandidate(value: '餐饮', label: '餐饮'),
            ],
          ),
        ],
      ),
    );
    expect(find.text('记为支出'), findsOneWidget);
    expect(find.text('记为收入'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(LedgerConfirmRow),
        matching: find.text('餐饮'),
      ),
      findsOneWidget,
      reason: '分类条也有「餐饮」，待确认行断言须限定在确认行内',
    );
    expect(find.text('忽略'), findsOneWidget);
  });

  testWidgets('test_ledger_page_confirm_resolves_and_removes_row',
      (tester) async {
    final repo = _FakeLedgerRepository(pending: [_pending(key: 'pk-1')]);
    await _openLedger(tester, repo);
    await tester.tap(find.text('确认'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(repo.confirmCalls, 1);
    expect(find.byType(LedgerConfirmRow), findsNothing);
  });

  testWidgets('test_ledger_page_confirm_failure_restores_row', (tester) async {
    final repo = _FakeLedgerRepository(
      pending: [_pending(key: 'pk-1')],
      confirmFails: true,
    );
    await _openLedger(tester, repo);
    await tester.tap(find.text('确认'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.byType(LedgerConfirmRow), findsOneWidget, reason: '失败要回滚');
    expect(find.textContaining('没处理成功'), findsOneWidget);
  });

  testWidgets('test_ledger_page_category_bars_cycle_four_gradients',
      (tester) async {
    await _openLedger(tester, _FakeLedgerRepository());
    final bars = tester.widgetList<CategoryBar>(find.byType(CategoryBar));
    expect(bars.length, 2);
    final gradients = bars.map((b) => b.gradient).toList();
    expect(gradients[0], isNot(gradients[1]),
        reason: '分类条按语义四色轮转，不是全 money');
  });

  testWidgets('test_ledger_page_existing_sections_unchanged', (tester) async {
    await _openLedger(tester, _FakeLedgerRepository());
    expect(find.text('¥128.50'), findsOneWidget);
    expect(find.text('本期共 2 笔。收入 0.00，结余 -128.50。'), findsOneWidget);
    expect(find.text('比上月同期少 12%'), findsOneWidget);
    expect(find.byType(CategoryBar), findsNWidgets(2));
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
  testWidgets('test_ledger_page_entry_row_colors_follow_category',
      (tester) async {
    final repo = _FakeLedgerRepository(
      entries: const [
        LedgerEntryData(
          id: 'e-9',
          amountText: '6.00',
          direction: 'expense',
          occurredAt: '今天 08:47',
          merchant: '地铁出行',
          categoryId: 'c-traffic',
        ),
        LedgerEntryData(
          id: 'e-10',
          amountText: '35.00',
          direction: 'expense',
          occurredAt: '今天 12:32',
          merchant: '一碗拉面',
          categoryId: 'c-unknown',
        ),
      ],
      categories: const [
        LedgerCategoryData(id: 'c-traffic', name: '交通', kind: 'expense'),
        LedgerCategoryData(id: 'c-food', name: '餐饮', kind: 'expense'),
      ],
    );
    await _openLedger(tester, repo);
  
    final rows = tester.widgetList<TxRow>(find.byType(TxRow)).toList();
    expect(rows[0].iconColor, AppColors.light.aiBlue, reason: '交通 → aiBlue');
    expect(rows[0].tileColor, AppColors.light.tileInfo);
    expect(rows[0].icon, AppIcons.train);
    expect(rows[1].iconColor, AppColors.light.money, reason: '未知分类回落 money');
    expect(rows[1].tileColor, AppColors.light.tileMoney);
  });
  
  test('test_ledger_category_visuals_maps_design_palette', () {
    const colors = AppColors.light;
    expect(ledgerCategoryVisuals(colors, '餐饮').fg, colors.money);
    expect(ledgerCategoryVisuals(colors, '交通').fg, colors.aiBlue);
    expect(ledgerCategoryVisuals(colors, '购物').fg, colors.aiPrimary);
    expect(ledgerCategoryVisuals(colors, '娱乐').fg, colors.health);
    expect(ledgerCategoryVisuals(colors, '人情').fg, colors.money,
        reason: '未识别分类回落基线');
    expect(ledgerCategoryVisuals(colors, null).icon, AppIcons.fileText);
  });
}
