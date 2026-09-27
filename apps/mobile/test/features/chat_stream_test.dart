import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/chat/domain/chat_page_state.dart' show ChatMessageItem;
import 'package:mobile/features/chat/domain/chat_turn_state.dart';
import 'package:mobile/core/network/events/chat_event.dart';
import 'package:mobile/design_system/components/incremental_markdown.dart';
import 'package:mobile/features/chat/presentation/streaming/chat_stream_controller.dart';
import 'package:mobile/features/chat/presentation/streaming/text_flush_buffer.dart';

void main() {
  test('token accumulates without per-token setState', () {
    var flushes = 0;
    final buffer = TextFlushBuffer(
      window: const Duration(milliseconds: 16),
      onFlush: (_) => flushes++,
    );
    for (var i = 0; i < 50; i++) {
      buffer.add('字');
    }
    expect(flushes, 0);
    expect(buffer.text, '字' * 50);
    buffer.flushNow();
    expect(flushes, 1);
    expect(buffer.flushedText, '字' * 50);
    buffer.dispose();
  });

  test('markdown splits closed and open tail', () {
    const md = IncrementalMarkdown();
    final (closed, open) = md.split('# 标题\n正文\n**未闭合');
    expect(closed, contains('# 标题'));
    expect(open, contains('**未闭合'));
    final (c2, o2) = md.split('```dart\nfinal a = 1;');
    expect(c2, isEmpty);
    expect(o2, contains('```dart'));
  });

  test('incomplete stream marked retryable', () {
    var state = reduceChatEvent(const ChatTurnState(), const ChatEvent.token(delta: 'hi'));
    state = markIncomplete(state);
    expect(state.incomplete, isTrue);
    expect(state.canRetry, isTrue);
    expect(state.status, ChatTurnStatus.failed);
  });

  test('done is not incomplete', () {
    var state = reduceChatEvent(const ChatTurnState(), const ChatEvent.token(delta: 'hi'));
    state = reduceChatEvent(state, const ChatEvent.done());
    state = markIncomplete(state);
    expect(state.incomplete, isFalse);
    expect(state.status, ChatTurnStatus.done);
  });

  test('reply_replace overrides accumulated text and pending buffer', () async {
    final controller = ChatStreamController(
      onState: (_) {},
      flushWindow: const Duration(milliseconds: 30),
    );
    final events = [
      const ChatEvent.token(delta: '别急'),
      const ChatEvent.token(delta: '，有我'),
      const ChatEvent.replyReplace(text: '别急，有我呢（已校准）'),
      const ChatEvent.done(),
    ];
    await controller.consume(Stream.fromIterable(events));
    expect(controller.state.text, '别急，有我呢（已校准）');
    expect(controller.state.status, ChatTurnStatus.done);
    controller.dispose();
  });

  test('tool steps upsert by step_id', () {
    var state = reduceChatEvent(
      const ChatTurnState(),
      const ChatEvent.toolStep(
        stepId: 's1',
        toolId: 't',
        label: '提取金额',
        status: 'running',
      ),
    );
    expect(state.toolSteps.length, 1);
    expect(state.status, ChatTurnStatus.toolRunning);
    state = reduceChatEvent(
      state,
      const ChatEvent.toolStep(
        stepId: 's1',
        toolId: 't',
        label: '提取金额',
        status: 'done',
        detail: '¥35',
      ),
    );
    expect(state.toolSteps.length, 1);
    expect(state.toolSteps.single.status, 'done');
    expect(state.toolSteps.single.detail, '¥35');
  });

  test('history payload with int row id parses (regression: 200 but no回显)', () {
    final item = ChatMessageItem.fromJson(const {
      'id': 11,
      'role': 'human',
      'content': 'hello',
      'created_at': '2026-09-27T23:07:41.437351',
    });
    expect(item.id, '11');
    expect(item.role, 'human');
    expect(item.content, 'hello');
    expect(item.createdAt, isNotNull);
    expect(ChatMessageItem.fromJson(const {}).id, '');
  });
}
