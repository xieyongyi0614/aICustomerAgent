import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:mobile/app/state/dynamic_tab.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/tokens/tokens.dart';
import 'package:mobile/features/home/data/home_repository.dart';
import 'package:mobile/features/home/presentation/home_page.dart';
import 'package:mobile/features/ledger/data/ledger_repository.dart';
import 'package:mobile/features/ledger/presentation/ledger_category_visuals.dart';
import 'package:mobile/features/ledger/presentation/ledger_page.dart';

/// 类目 id 用真实形态（雪花十进制串）：后端 `by_category` 下发的是 id，
/// 名称靠 `GET /ledger/categories` 的 id→名称映射解析——假数据若直接用中文名当
/// id，会把「分类条显示 id」这种缺陷掩盖掉。
const _categoryFoodId = '100991278912634880';
const _categoryTrafficId = '100991279118155776';

const _categories = [
  LedgerCategoryData(id: _categoryFoodId, name: '餐饮', kind: 'expense'),
  LedgerCategoryData(id: _categoryTrafficId, name: '交通', kind: 'expense'),
];

const _summary = LedgerSummaryData(
  periodLabel: '2026年9月',
  expenseText: '128.50',
  incomeText: '0.00',
  netText: '-128.50',
  entryCount: 2,
  byCategory: [
    LedgerCategoryTotal(
      categoryId: _categoryFoodId,
      expenseMinor: 12850,
      incomeMinor: 0,
    ),
    LedgerCategoryTotal(
      categoryId: _categoryTrafficId,
      expenseMinor: 8600,
      incomeMinor: 0,
    ),
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
    this.categories = _categories,
    this.summary = _summary,
    this.summaryFails = false,
  }) : super(dio: Dio());

  final int autoCount;
  final bool autoFails;
  final bool summaryFails;
  final LedgerSummaryData summary;
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
    if (summaryFails) throw Exception('summary down');
    return summary;
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

HomeSummaryData _homeSummary() => const HomeSummaryData(
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

/// 复刻真实壳层：入口一律 push（栈里有历史），返回即弹栈回各自的来路页。
GoRouter _routerWithOrigins(
  LedgerRepository repo, {
  String initial = '/home',
}) =>
    GoRouter(
      initialLocation: initial,
      routes: [
        GoRoute(
          path: '/home',
          builder: (_, _) => HomePage(debugSummary: _homeSummary()),
        ),
        GoRoute(
          path: '/life',
          builder: (context, _) => Scaffold(
            body: Center(
              child: TextButton(
                onPressed: () =>
                    context.push<bool>(LifeModule.ledger.routePath),
                child: const Text('OPEN_LEDGER_FROM_LIFE'),
              ),
            ),
          ),
        ),
        GoRoute(
          path: '/ledger',
          builder: (_, state) => LedgerPage(
            repository: repo,
            backLabel: state.extra as String? ?? '生活',
          ),
        ),
      ],
    );

Future<void> _openLedgerViaOrigins(
  WidgetTester tester,
  LedgerRepository repo, {
  String initial = '/home',
}) async {
  tester.view.physicalSize = const Size(390, 2000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp.router(
      routerConfig: _routerWithOrigins(repo, initial: initial),
      theme: buildAppTheme(),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

/// 首页带常驻动画（Orb），pumpAndSettle 永不收敛，按固定时长推进转场。
Future<void> _settleRoute(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(seconds: 1));
}

/// 返回链的 GestureDetector 走 deferToChild：只有图标 / 文字命中，点整块会落空。
Finder _backLink(String label) => find.descendant(
  of: find.byType(BackLink),
  matching: find.text(label),
);

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

  testWidgets('test_ledger_page_category_bars_show_names_not_ids',
      (tester) async {
    final repo = _FakeLedgerRepository(
      summary: const LedgerSummaryData(
        periodLabel: '2026年10月',
        expenseText: '8.00',
        incomeText: '0.00',
        netText: '-8.00',
        entryCount: 2,
        byCategory: [
          LedgerCategoryTotal(
            categoryId: _categoryFoodId,
            expenseMinor: 800,
            incomeMinor: 0,
          ),
          LedgerCategoryTotal(categoryId: null, expenseMinor: 100, incomeMinor: 0),
          LedgerCategoryTotal(
            categoryId: '100999999999999999',
            expenseMinor: 50,
            incomeMinor: 0,
          ),
        ],
      ),
    );
    await _openLedger(tester, repo);

    final bars =
        tester.widgetList<CategoryBar>(find.byType(CategoryBar)).toList();
    expect(bars[0].label, '餐饮', reason: 'A19 分类条标题是类目名称，不是类目 id');
    expect(bars[1].label, '未分类');
    expect(
      bars[2].label,
      '未分类',
      reason: '映射缺失（类目已删 / 名称未拉回）统一降级，绝不把 id 当文案',
    );
    expect(
      find.text(_categoryFoodId),
      findsNothing,
      reason: '雪花 id 不应出现在页面上任何位置',
    );
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

  testWidgets('test_ledger_page_entry_time_is_formatted_local', (tester) async {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day, 12, 32);
    final yesterday = today.subtract(const Duration(days: 1));
    final older = today.subtract(const Duration(days: 3));
    // 接口下发 UTC ISO 串（真实形态），页面必须转本地时区并按 B5 §11 格式化
    final todayIso = today.toUtc().toIso8601String();
    final yesterdayIso = yesterday.toUtc().toIso8601String();
    final olderIso = older.toUtc().toIso8601String();
    final olderPattern = older.year == now.year ? 'M/d HH:mm' : 'yyyy/M/d HH:mm';

    await _openLedger(
      tester,
      _FakeLedgerRepository(
        entries: [
          LedgerEntryData(
            id: 'e-today',
            amountText: '35.00',
            direction: 'expense',
            occurredAt: todayIso,
            merchant: '一碗拉面',
          ),
          LedgerEntryData(
            id: 'e-yesterday',
            amountText: '6.00',
            direction: 'expense',
            occurredAt: yesterdayIso,
            merchant: '地铁出行',
          ),
          LedgerEntryData(
            id: 'e-older',
            amountText: '87.00',
            direction: 'expense',
            occurredAt: olderIso,
            merchant: '咖啡豆',
          ),
        ],
      ),
    );

    expect(find.text('今天 12:32'), findsOneWidget);
    expect(find.text('昨天 12:32'), findsOneWidget);
    expect(find.text(DateFormat(olderPattern).format(older)), findsOneWidget);
    for (final iso in [todayIso, yesterdayIso, olderIso]) {
      expect(find.text(iso), findsNothing, reason: '不得直接把接口 ISO 串当副文案');
    }
  });

  testWidgets('test_ledger_page_prefers_server_time_label', (tester) async {
    // 设备时区不可靠：模拟器默认 UTC，本地 00:23 的账曾显示成「今天 16:23」。
    // 服务端按产品时区下发 occurred_label，端上不得再按设备时区自行换算覆盖。
    await _openLedger(
      tester,
      _FakeLedgerRepository(
        entries: const [
          LedgerEntryData(
            id: 'e-server-label',
            amountText: '35.00',
            direction: 'expense',
            occurredAt: '2026-10-06T16:23:03.906523+00:00',
            occurredLabel: '今天 00:23',
            merchant: '一碗拉面',
          ),
        ],
      ),
    );

    expect(find.text('今天 00:23'), findsOneWidget);
    expect(find.text('今天 16:23'), findsNothing);
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

  testWidgets('test_ledger_page_back_from_home_returns_home', (tester) async {
    await _openLedgerViaOrigins(tester, _FakeLedgerRepository());

    await tester.tap(find.text('查看账本 ›'));
    await _settleRoute(tester);
    expect(find.byType(LedgerPage), findsOneWidget);

    expect(
      _backLink('首页'),
      findsOneWidget,
      reason: '从首页进来，返回链要写来路页名',
    );
    await tester.tap(_backLink('首页'));
    await _settleRoute(tester);

    expect(find.text('今日任务'), findsOneWidget, reason: '从首页进来要回首页');
    expect(find.byType(LedgerPage), findsNothing);
  });

  testWidgets('test_ledger_page_back_from_life_returns_life', (tester) async {
    await _openLedgerViaOrigins(
      tester,
      _FakeLedgerRepository(),
      initial: '/life',
    );

    await tester.tap(find.text('OPEN_LEDGER_FROM_LIFE'));
    await _settleRoute(tester);
    expect(find.byType(LedgerPage), findsOneWidget);

    expect(
      _backLink('生活'),
      findsOneWidget,
      reason: '生活宫格入口不带来路，回落默认「生活」',
    );
    await tester.tap(_backLink('生活'));
    await _settleRoute(tester);

    expect(
      find.text('OPEN_LEDGER_FROM_LIFE'),
      findsOneWidget,
      reason: '从生活页进来要回生活页',
    );
  });

  testWidgets('test_ledger_page_error_state_keeps_back_link', (tester) async {
    await _openLedgerViaOrigins(
      tester,
      _FakeLedgerRepository(summaryFails: true),
    );

    await tester.tap(find.text('查看账本 ›'));
    await _settleRoute(tester);

    expect(find.byType(ErrorState), findsOneWidget);
    expect(
      _backLink('首页'),
      findsOneWidget,
      reason: '错误态也要留返回入口，否则 Tab 栏已隐藏、用户被困在页内',
    );

    await tester.tap(_backLink('首页'));
    await _settleRoute(tester);
    expect(find.text('今日任务'), findsOneWidget);
  });
}
