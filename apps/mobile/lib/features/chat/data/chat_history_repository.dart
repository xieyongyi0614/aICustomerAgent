import 'package:dio/dio.dart';
import 'package:drift/drift.dart' show OrderingTerm;

import '../../../core/network/dio_client.dart';
import '../../../core/network/interceptors/token_reader.dart';
import '../../../core/storage/cache_db.dart';
import '../../../core/storage/secure_token_store.dart';
import '../domain/chat_page_state.dart' show ChatMessageItem;

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

/// 远程会话历史（GET /conversations/{id}/messages 与 /conversations/latest）。
class ChatHistoryRemoteRepository {
  ChatHistoryRemoteRepository({Dio? dio, TokenReader? tokenReader})
      : _dio = dio ??
            createDio(
              tokenReader: tokenReader ?? SecureTokenStore(),
            );

  final Dio _dio;

  /// 最新会话整页；无历史会话（404）→ null。
  Future<ChatHistoryPage?> latest({int limit = 200}) async {
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/conversations/latest',
        queryParameters: {'limit': limit},
      );
      return _toPage(res.data!);
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) return null;
      rethrow;
    }
  }

  /// 指定会话整页；会话不存在（404）→ null。
  Future<ChatHistoryPage?> messages(String conversationId,
      {int limit = 200}) async {
    try {
      final res = await _dio.get<Map<String, dynamic>>(
        '/conversations/$conversationId/messages',
        queryParameters: {'limit': limit},
      );
      return _toPage(res.data!);
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) return null;
      rethrow;
    }
  }

  ChatHistoryPage _toPage(Map<String, dynamic> json) {
    final items = (json['messages'] as List<dynamic>? ?? const [])
        .map((e) => ChatMessageItem.fromJson(e as Map<String, dynamic>))
        .toList();
    return ChatHistoryPage(
      conversationId: json['conversation_id'] as String? ?? '',
      messages: items,
    );
  }
}

class ChatHistoryPage {
  const ChatHistoryPage({required this.conversationId, required this.messages});

  final String conversationId;
  final List<ChatMessageItem> messages;
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
