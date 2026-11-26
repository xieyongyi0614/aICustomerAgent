import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/features/chat/data/chat_ledger_repository.dart';
import 'package:mobile/features/chat/domain/chat_page_state.dart';
import 'package:mobile/features/chat/presentation/chat_ledger_page.dart';

const _summary = ChatLedgerSummary(
  periodLabel: '本月',
  expenseText: '1,240.00',
  entryCount: 12,
  comparisonLabel: '比上月同期少 8%',
);

Future<GoRouter> _pump(WidgetTester tester, ChatLedgerPage page) async {
  final router = GoRouter(
    initialLocation: '/chat/ledger',
    routes: [
      GoRoute(path: '/chat', builder: (_, _) => const Scaffold(body: Text('CHAT'))),
      GoRoute(path: '/chat/ledger', builder: (_, _) => page),
      GoRoute(path: '/ledger', builder: (_, _) => const Scaffold(body: Text('LEDGER'))),
    ],
  );
  await tester.pumpWidget(
    MaterialApp.router(theme: buildAppTheme(), routerConfig: router),
  );
  return router;
}

void main() {
  testWidgets('renders conversation messages and the real month summary',
      (tester) async {
    await _pump(
      tester,
      ChatLedgerPage(
        conversationId: 'c-1',
        loader: (id) async => const ChatLedgerData(
          messages: [
            ChatMessageItem(id: 'm1', role: 'user', content: '午饭 35 元'),
            ChatMessageItem(id: 'm2', role: 'ai', content: '已记下，本月餐饮 ¥1,240'),
          ],
          summary: _summary,
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('午饭 35 元'), findsOneWidget);
    expect(find.text('已记下，本月餐饮 ¥1,240'), findsOneWidget);
    expect(find.text('¥1,240.00'), findsOneWidget);
    expect(find.text('支出 · 12 笔'), findsOneWidget);
    expect(find.text('比上月同期少 8%'), findsOneWidget);
  });

  testWidgets('empty conversation shows the honest empty state', (tester) async {
    await _pump(
      tester,
      ChatLedgerPage(
        conversationId: 'c-1',
        loader: (id) async => const ChatLedgerData(messages: []),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('这个会话还没有记账记录'), findsOneWidget);
    expect(find.text('工具调用 · 记账 Skill'), findsNothing);
  });

  testWidgets('load failure surfaces a retry that re-queries', (tester) async {
    var calls = 0;
    await _pump(
      tester,
      ChatLedgerPage(
        conversationId: 'c-1',
        loader: (id) async {
          calls += 1;
          if (calls == 1) throw Exception('boom');
          return const ChatLedgerData(
            messages: [ChatMessageItem(id: 'm1', role: 'user', content: '打车 22')],
          );
        },
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('我这边有点小问题，稍后再试'), findsOneWidget);
    await tester.tap(find.text('再试一次'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(calls, 2);
    expect(find.text('打车 22'), findsOneWidget);
  });

  testWidgets('missing conversation id does not call the backend',
      (tester) async {
    var calls = 0;
    await _pump(
      tester,
      ChatLedgerPage(
        loader: (id) async {
          calls += 1;
          return const ChatLedgerData(messages: []);
        },
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(calls, 0);
    expect(find.text('这个会话还没有记账记录'), findsOneWidget);
  });
}
