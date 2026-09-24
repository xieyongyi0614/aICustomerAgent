import 'dart:async';
import 'dart:convert';

import '../errors/app_error.dart';
import '../events/chat_event.dart';
import '../events/chat_event_parser.dart';

/// NDJSON：utf8 → LineSplitter → jsonDecode → ChatEvent
/// 跨 chunk 半行由 LineSplitter 缓冲；空行跳过；非法 JSON 记 failure 不中断。
class NdjsonParser {
  const NdjsonParser();

  Stream<ChatEvent> parse(Stream<List<int>> byteStream) async* {
    final lines = utf8.decoder.bind(byteStream).transform(const LineSplitter());
    await for (final line in lines) {
      final trimmed = line.trim();
      if (trimmed.isEmpty) continue;
      try {
        final map = jsonDecode(trimmed) as Map<String, dynamic>;
        yield parseChatEvent(map);
      } on FormatException catch (e) {
        yield ChatEvent.failure(detail: 'parse', error: e.message);
      } catch (e) {
        yield ChatEvent.failure(detail: 'parse', error: '$e');
      }
    }
  }

  Stream<String> lines(Stream<List<int>> byteStream) =>
      utf8.decoder.bind(byteStream).transform(const LineSplitter());
}

/// 断流检测：done 未到即结束 → streamInterrupted
class ChatStreamMonitor {
  bool _done = false;

  void onEvent(ChatEvent event) {
    if (event is Done) _done = true;
  }

  AppError? incompleteError() => _done ? null : AppError.streamInterrupted();
}
