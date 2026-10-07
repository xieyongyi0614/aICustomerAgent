import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/features/life/presentation/capture_route.dart';

/// 记录注入路由收到的调用，便于断言「归到哪一类」。
class _RouterSpy {
  final calls = <(CaptureRouteKind, String)>[];

  Future<CaptureRouteResult> call(CaptureRouteKind kind, String text) async {
    calls.add((kind, text));
    final label = kind == CaptureRouteKind.task ? '任务' : '备忘录';
    return CaptureRouteResult(receipt: '已归到「$label」', taskId: 't-1');
  }
}

Future<GoRouter> _pumpSheet(
  WidgetTester tester, {
  required CaptureRouter router,
  Future<void> Function(String taskId)? reclassify,
}) async {
  final goRouter = GoRouter(
    initialLocation: '/life',
    routes: [
      GoRoute(
        path: '/life',
        builder: (_, _) => Scaffold(
          body: Builder(
            builder: (ctx) => Center(
              child: TextButton(
                onPressed: () => showModalBottomSheet<void>(
                  context: ctx,
                  isScrollControlled: true,
                  builder: (_) => CaptureRouteSheet(
                    initialText: '午饭 35 元',
                    debugRouter: router,
                    debugReclassify: reclassify,
                  ),
                ),
                child: const Text('OPEN'),
              ),
            ),
          ),
        ),
      ),
      GoRoute(
        path: '/chat',
        builder: (_, state) => Scaffold(body: Text('CHAT:${state.extra}')),
      ),
    ],
  );
  await tester.pumpWidget(
    MaterialApp.router(theme: buildAppTheme(), routerConfig: goRouter),
  );
  await tester.tap(find.text('OPEN'));
  await tester.pumpAndSettle();
  return goRouter;
}

void main() {
  testWidgets('capture sheet offers three explicit targets', (tester) async {
    final spy = _RouterSpy();
    await _pumpSheet(tester, router: spy.call);

    expect(find.text('快速捕获'), findsOneWidget);
    expect(find.text('记账'), findsOneWidget);
    expect(find.text('任务'), findsOneWidget);
    expect(find.text('备忘录'), findsOneWidget);
  });

  testWidgets('task target lands in task domain and can be reclassified',
      (tester) async {
    final spy = _RouterSpy();
    final reclassified = <String>[];
    await _pumpSheet(
      tester,
      router: spy.call,
      reclassify: (taskId) async => reclassified.add(taskId),
    );

    await tester.tap(find.text('任务'));
    await tester.pumpAndSettle();

    expect(spy.calls, [(CaptureRouteKind.task, '午饭 35 元')]);
    expect(find.text('已归到「任务」'), findsOneWidget);
    expect(find.text('改归'), findsOneWidget);

    await tester.tap(find.text('改归'));
    await tester.pumpAndSettle();

    expect(reclassified, ['t-1']);
    expect(find.text('已归到「任务」'), findsNothing);
    expect(find.text('记账'), findsOneWidget);
  });

  testWidgets('ledger target hands the sentence to the chat page',
      (tester) async {
    final spy = _RouterSpy();
    await _pumpSheet(tester, router: spy.call);

    await tester.tap(find.text('记账'));
    await tester.pumpAndSettle();

    expect(spy.calls, isEmpty);
    expect(find.text('CHAT:午饭 35 元'), findsOneWidget);
    expect(find.text('快速捕获'), findsNothing);
  });

  testWidgets('empty input is rejected without calling the backend',
      (tester) async {
    final spy = _RouterSpy();
    await _pumpSheet(tester, router: spy.call);

    await tester.enterText(find.byType(TextField), '   ');
    await tester.tap(find.text('任务'));
    await tester.pump();

    expect(spy.calls, isEmpty);
    expect(find.text('先写一句话，再选归到哪里'), findsOneWidget);
  });

  testWidgets('double submit within one frame lands a single task',
      (tester) async {
    final pending = Completer<CaptureRouteResult>();
    var calls = 0;
    await _pumpSheet(tester, router: (kind, text) {
      calls++;
      return pending.future;
    });

    await tester.tap(find.text('任务'));
    await tester.tap(find.text('任务'), warnIfMissed: false);
    await tester.pump();

    expect(calls, 1, reason: '同一次提交在途时不得再发一次');

    pending.complete(
      const CaptureRouteResult(receipt: '已归到「任务」', taskId: 't-1'),
    );
    await tester.pumpAndSettle();
    expect(find.text('已归到「任务」'), findsOneWidget);
  });
}
