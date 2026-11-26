import 'package:freezed_annotation/freezed_annotation.dart';

part 'chat_event.freezed.dart';

/// 对话 NDJSON 事件 union（5 类）。
/// switch 必须无 default，后端新增类型 → 编译期失败（fail-closed 对侧）。
/// JSON 解析见 chat_event_parser.dart（未知 type 抛 FormatException）。
@freezed
sealed class ChatEvent with _$ChatEvent {
  const factory ChatEvent.turnMeta({
    String? roleMode,
    String? analysis,
    String? sceneId,
    String? sceneLabel,
    String? intention,
    String? currentGoal,
    String? behavior,
    String? mode,
    String? actionIntent,
    MemoryRefs? memoryRefs,
  }) = TurnMeta;

  const factory ChatEvent.token({required String delta}) = TokenDelta;

  /// grounding 重写后的整段替换文本；到达后覆盖已渲染的流式文本。
  const factory ChatEvent.replyReplace({required String text}) = ReplyReplace;

  const factory ChatEvent.toolStep({
    required String stepId,
    required String toolId,
    required String label,
    required String status,
    String? detail,
    String? target,
  }) = ToolStep;

  const factory ChatEvent.done() = Done;

  const factory ChatEvent.failure({
    String? detail,
    String? error,
  }) = Failure;
}

class MemoryRef {
  const MemoryRef({required this.id, required this.kind, required this.label});

  final String id;
  final String kind;
  final String label;

  factory MemoryRef.fromJson(Map<String, dynamic> json) => MemoryRef(
        id: json['id'] as String? ?? '',
        kind: json['kind'] as String? ?? '',
        label: json['label'] as String? ?? '',
      );
}

/// 包装类型，避免 freezed 为 List 字段生成非法构造参数。
class MemoryRefs {
  const MemoryRefs(this.items);

  final List<MemoryRef> items;

  int get length => items.length;
}
