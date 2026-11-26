import 'dart:async';

import '../../../../core/network/events/chat_event.dart';
import '../../../../core/network/ndjson/ndjson_parser.dart';
import '../../domain/chat_turn_state.dart';
import 'text_flush_buffer.dart';

/// 消费 ChatEvent 流 → ChatTurnState；dispose 必须触发取消回调。
class ChatStreamController {
  ChatStreamController({
    required this.onState,
    Duration flushWindow = const Duration(milliseconds: 16),
  }) {
    _buffer = TextFlushBuffer(
      window: flushWindow,
      onFlush: (_) => _emit(),
    );
  }

  final void Function(ChatTurnState state) onState;
  late final TextFlushBuffer _buffer;
  final ChatStreamMonitor _monitor = ChatStreamMonitor();
  void Function()? _onCancel;

  ChatTurnState _state = const ChatTurnState();
  bool _disposed = false;

  ChatTurnState get state => _state;

  /// 数据层注入取消动作（CancelToken 由 core/network 持有，不进 presentation）。
  void attachCancel(void Function() onCancel) => _onCancel = onCancel;

  Future<void> consume(Stream<ChatEvent> events) async {
    await for (final event in events) {
      if (_disposed) return;
      _apply(event);
    }
    if (_disposed) return;
    final incomplete = _monitor.incompleteError();
    if (incomplete != null) {
      _buffer.flushNow();
      _state = markIncomplete(_state.copyWith(text: _buffer.flushedText));
      _emit();
    }
  }

  void _apply(ChatEvent event) {
    _monitor.onEvent(event);
    if (event is TokenDelta) {
      _buffer.add(event.delta);
      return;
    }
    if (event is ReplyReplace) {
      _buffer.replaceWith(event.text);
      _state = reduceChatEvent(_state.copyWith(text: event.text), event);
      _emit();
      return;
    }
    if (event is Done) {
      _buffer.flushNow();
      _state = reduceChatEvent(_state.copyWith(text: _buffer.flushedText), event);
      _emit();
      return;
    }
    _buffer.flushNow();
    _state = reduceChatEvent(_state.copyWith(text: _buffer.flushedText), event);
    _emit();
  }

  void _emit() {
    if (_disposed) return;
    onState(_state.copyWith(text: _buffer.text));
  }

  void dispose() {
    _disposed = true;
    _buffer.dispose();
    _onCancel?.call();
    _onCancel = null;
  }
}
