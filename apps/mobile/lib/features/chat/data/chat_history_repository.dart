import 'package:drift/drift.dart' show OrderingTerm;

import '../../../core/storage/cache_db.dart';

/// 会话历史只读缓存投影（服务端 DTO 字段）。
class ChatHistoryCache {
  ChatHistoryCache(this._db);

  final AppCacheDb _db;

  Future<List<ChatMessageItem>> loadMessages(String conversationId) async {
    final rows = await (_db.select(_db.sessionMessages)
          ..where((t) => t.conversationId.equals(conversationId))
          ..orderBy([(t) => OrderingTerm.asc(t.eventTime)]))
        .get();
    return rows
        .map(
          (r) => ChatMessageItem(
            id: r.messageId,
            role: r.role,
            content: r.content,
            createdAt: r.eventTime,
          ),
        )
        .toList();
  }

  Future<void> replaceMessages(
    String conversationId,
    List<ChatMessageItem> items,
  ) async {
    await _db.transaction(() async {
      await (_db.delete(_db.sessionMessages)
            ..where((t) => t.conversationId.equals(conversationId)))
          .go();
      for (final m in items) {
        await _db.into(_db.sessionMessages).insertOnConflictUpdate(
              SessionMessagesCompanion.insert(
                conversationId: conversationId,
                messageId: m.id,
                role: m.role,
                content: m.content,
                eventTime: m.createdAt ?? DateTime.now(),
                cachedAt: DateTime.now(),
              ),
            );
      }
    });
  }
}

class ChatMessageItem {
  const ChatMessageItem({
    required this.id,
    required this.role,
    required this.content,
    this.createdAt,
  });

  final String id;
  final String role;
  final String content;
  final DateTime? createdAt;
}

/// 会话列表：端上投影（无专用列表端点，D3）。
abstract interface class ChatSessionSource {
  Future<List<ChatSessionSummary>> listSessions();
}

class LocalSessionSource implements ChatSessionSource {
  LocalSessionSource(this._known);

  final List<ChatSessionSummary> _known;

  @override
  Future<List<ChatSessionSummary>> listSessions() async => _known;
}

class ChatSessionSummary {
  const ChatSessionSummary({
    required this.id,
    this.title = '对话',
    this.updatedAt,
  });

  final String id;
  final String title;
  final DateTime? updatedAt;
}
