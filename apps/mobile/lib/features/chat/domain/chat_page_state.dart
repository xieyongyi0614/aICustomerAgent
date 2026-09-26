import '../../../core/network/events/chat_event.dart';
import 'chat_turn_state.dart';

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

  factory ChatMessageItem.fromJson(Map<String, dynamic> json) => ChatMessageItem(
        id: json['id'] as String? ?? '',
        role: json['role'] as String? ?? 'ai',
        content: json['content'] as String? ?? '',
        createdAt: json['created_at'] == null
            ? null
            : DateTime.tryParse(json['created_at'] as String),
      );
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

class ChatPageState {
  const ChatPageState({
    this.loading = true,
    this.error,
    this.sessions = const [],
    this.messages = const [],
    this.memoryRefs = const [],
    this.currentSessionId,
    this.streamingText = '',
    this.toolSteps = const [],
    this.lastUserText,
  });

  final bool loading;
  final Object? error;
  final List<ChatSessionSummary> sessions;
  final List<ChatMessageItem> messages;

  /// 键缺省语义：空列表 = 不渲染提示条（与 API-003 对齐）
  final List<MemoryRef> memoryRefs;
  final String? currentSessionId;
  final String streamingText;
  final List<ChatToolStep> toolSteps;
  final String? lastUserText;

  bool get streaming => streamingText.isNotEmpty;

  bool get showMemoryHint => memoryRefs.isNotEmpty;

  String get memoryHintText {
    final labels = memoryRefs.map((e) => e.label).join(' · ');
    return '本轮对话已调用 ${memoryRefs.length} 条长期记忆：$labels';
  }

  ChatPageState copyWith({
    bool? loading,
    Object? error,
    List<ChatSessionSummary>? sessions,
    List<ChatMessageItem>? messages,
    List<MemoryRef>? memoryRefs,
    String? currentSessionId,
    String? streamingText,
    List<ChatToolStep>? toolSteps,
    String? lastUserText,
  }) {
    return ChatPageState(
      loading: loading ?? this.loading,
      error: error ?? this.error,
      sessions: sessions ?? this.sessions,
      messages: messages ?? this.messages,
      memoryRefs: memoryRefs ?? this.memoryRefs,
      currentSessionId: currentSessionId ?? this.currentSessionId,
      streamingText: streamingText ?? this.streamingText,
      toolSteps: toolSteps ?? this.toolSteps,
      lastUserText: lastUserText ?? this.lastUserText,
    );
  }
}
