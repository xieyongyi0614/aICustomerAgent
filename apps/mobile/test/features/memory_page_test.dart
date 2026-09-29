import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/features/memory/data/memory_repository.dart';
import 'package:mobile/features/memory/presentation/memory_page.dart';

/// 零依赖的 Dio 传输层替身：按请求返回固定 JSON，并记录收到的请求体。
class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.responder);

  final ResponseBody Function(RequestOptions options) responder;
  final List<RequestOptions> requests = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    requests.add(options);
    return responder(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _json(Object payload) => ResponseBody.fromString(
      jsonEncode(payload),
      200,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );

MemoryItemData _item({
  String id = 'm1',
  String kind = 'preference',
  String type = 'user_preference',
  String typeLabel = '偏好',
  String content = '喜欢海边旅行',
  String sourceKind = 'conversation',
  String sourceLabel = '对话提及',
  int sourceCount = 6,
  String? lastUpdated,
  List<MemoryReceiptData> receipts = const [],
}) =>
    MemoryItemData(
      id: id,
      kind: kind,
      type: type,
      typeLabel: typeLabel,
      content: content,
      sourceKind: sourceKind,
      sourceLabel: sourceLabel,
      sourceCount: sourceCount,
      lastUpdated: lastUpdated,
      usageReceipts: receipts,
    );

MemoryItemsData _data(List<MemoryGroupData> groups, {int? total}) => MemoryItemsData(
      generatedAt: '2026-09-29T10:00:00',
      total: total ?? groups.fold(0, (sum, g) => sum + g.items.length),
      addedThisWeek: 6,
      groups: groups,
    );

void main() {
  group('MemoryRepository 契约解析', () {
    test('listItems 解析分组信封与用途回执', () async {
      final adapter = _FakeAdapter(
        (_) => _json({
          'generated_at': '2026-09-29T10:00:00',
          'total': 2,
          'added_this_week': 1,
          'degraded': false,
          'groups': [
            {
              'kind': 'preference',
              'label': '长期偏好',
              'items': [
                {
                  'id': 'm1',
                  'kind': 'preference',
                  'type': 'user_preference',
                  'type_label': '偏好',
                  'content': '喜欢海边旅行',
                  'source_kind': 'conversation',
                  'source_label': '对话提及',
                  'source_count': 6,
                  'last_updated': '2026-09-21T08:00:00',
                  'usage_receipts': [
                    {
                      'kind': 'recall_autonomy',
                      'label': '已用于任务排序',
                      'ts': '2026-09-28T09:00:00',
                      'ref': 't1',
                    },
                  ],
                },
              ],
            },
            {'kind': 'habit', 'label': '习惯', 'items': []},
            {'kind': 'goal', 'label': '目标', 'items': []},
            {
              'kind': 'now',
              'label': '当下',
              'items': [
                {
                  'id': 'm2',
                  'kind': 'now',
                  'type': 'relationship_fact',
                  'type_label': '关系',
                  'content': '习惯睡前聊两句',
                  'source_kind': 'conversation',
                  'source_label': '对话提及',
                  'source_count': 1,
                  'last_updated': null,
                  'usage_receipts': [],
                },
              ],
            },
          ],
        }),
      );
      final dio = Dio()..httpClientAdapter = adapter;
      final repo = MemoryRepository(dio: dio);

      final data = await repo.listItems();

      expect(adapter.requests.single.path, '/memory/items');
      expect(data.total, 2);
      expect(data.addedThisWeek, 1);
      expect(data.degraded, isFalse);
      expect(data.groups.map((g) => g.label).toList(),
          ['长期偏好', '习惯', '目标', '当下']);
      expect(data.allItems.length, 2);

      final first = data.allItems.first;
      expect(first.sourceLabel, '对话提及');
      expect(first.sourceCount, 6);
      expect(first.typeLabel, '偏好');
      expect(first.usageReceipts.single.label, '已用于任务排序');
      expect(first.usageReceipts.single.ref, 't1');
    });

    test('updateContent 发送编辑后的正文并回解更新项', () async {
      final adapter = _FakeAdapter(
        (_) => _json({
          'id': 'm1',
          'kind': 'preference',
          'type': 'user_preference',
          'type_label': '偏好',
          'content': '改成了新的偏好',
          'source_kind': 'conversation',
          'source_label': '对话提及',
          'source_count': 6,
          'last_updated': '2026-09-29T12:00:00',
          'usage_receipts': [],
        }),
      );
      final dio = Dio()..httpClientAdapter = adapter;
      final repo = MemoryRepository(dio: dio);

      final updated = await repo.updateContent('m1', '改成了新的偏好');

      final sent = adapter.requests.single;
      expect(sent.method, 'PATCH');
      expect(sent.path, '/memory/items/m1');
      expect(sent.data, {'content': '改成了新的偏好'});
      expect(updated.content, '改成了新的偏好');
    });

    test('forget 走遗忘端点', () async {
      final adapter = _FakeAdapter(
        (_) => _json({'id': 'm1', 'status': 'forgotten', 'forgotten_at': 'now'}),
      );
      final dio = Dio()..httpClientAdapter = adapter;
      final repo = MemoryRepository(dio: dio);

      await repo.forget('m1');

      final sent = adapter.requests.single;
      expect(sent.method, 'POST');
      expect(sent.path, '/memory/items/m1/forget');
    });
  });

  group('MemoryPage 渲染与编辑', () {
    Future<void> pump(WidgetTester tester, MemoryItemsData data,
        {Future<MemoryItemData> Function(String, String)? update}) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: MemoryPage(debugData: data, debugUpdate: update),
        ),
      );
      await tester.pump();
    }

    testWidgets('按服务端分组渲染，空组不留白', (tester) async {
      await pump(
        tester,
        _data([
          MemoryGroupData(kind: 'preference', label: '长期偏好', items: [
            _item(lastUpdated: '2026-09-21T08:00:00'),
          ]),
          const MemoryGroupData(kind: 'habit', label: '习惯', items: []),
          const MemoryGroupData(kind: 'goal', label: '目标', items: []),
          MemoryGroupData(kind: 'now', label: '当下', items: [
            _item(
              id: 'm2',
              kind: 'now',
              typeLabel: '关系',
              content: '习惯睡前聊两句',
              sourceCount: 1,
            ),
          ]),
        ]),
      );

      expect(find.text('2 条 · 本周 +6'), findsOneWidget);
      expect(find.text('长期偏好'), findsOneWidget);
      expect(find.text('当下'), findsOneWidget);
      expect(find.text('习惯'), findsNothing);
      expect(find.text('目标'), findsNothing);
      expect(find.text('来源：6 次对话提及 · 最近更新 9/21'), findsOneWidget);
      expect(find.text('来源：1 次对话提及'), findsOneWidget);
    });

    testWidgets('用途回执按服务端文案渲染', (tester) async {
      await pump(
        tester,
        _data([
          MemoryGroupData(kind: 'habit', label: '习惯', items: [
            _item(
              typeLabel: '习惯',
              sourceLabel: '任务完成',
              receipts: const [
                MemoryReceiptData(kind: 'recall_autonomy', label: '已用于任务排序'),
              ],
            ),
          ]),
        ]),
      );

      expect(find.text('已用于任务排序'), findsOneWidget);
    });

    testWidgets('空记忆走空态', (tester) async {
      await pump(tester, _data(const []));
      expect(find.text('还没有记住什么，多聊聊就好'), findsOneWidget);
      expect(find.text('0 条 · 本周 +6'), findsOneWidget);
    });

    testWidgets('编辑弹窗预填原文，保存时把新正文交给后端', (tester) async {
      final saved = <(String, String)>[];
      await pump(
        tester,
        _data([
          MemoryGroupData(kind: 'preference', label: '长期偏好', items: [
            _item(content: '喜欢海边旅行'),
          ]),
        ]),
        update: (id, content) async {
          saved.add((id, content));
          return _item(content: content);
        },
      );

      await tester.tap(find.text('编辑'));
      await tester.pumpAndSettle();

      final field = tester.widget<TextField>(find.byType(TextField));
      expect(field.controller?.text, '喜欢海边旅行');

      await tester.enterText(find.byType(TextField), '更喜欢山里');
      await tester.tap(find.text('保存'));
      await tester.pumpAndSettle();

      expect(saved, [('m1', '更喜欢山里')]);
    });

    testWidgets('正文没改时不发请求', (tester) async {
      var calls = 0;
      await pump(
        tester,
        _data([
          MemoryGroupData(kind: 'preference', label: '长期偏好', items: [
            _item(content: '喜欢海边旅行'),
          ]),
        ]),
        update: (id, content) async {
          calls += 1;
          return _item(content: content);
        },
      );

      await tester.tap(find.text('编辑'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('保存'));
      await tester.pumpAndSettle();

      expect(calls, 0);
    });
  });
}
