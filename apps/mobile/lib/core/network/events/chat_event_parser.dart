import 'chat_event.dart';

/// NDJSON 行 → ChatEvent。未知 type fail-closed（FormatException）。
ChatEvent parseChatEvent(Map<String, dynamic> json) {
  final type = json['type'] as String?;
  switch (type) {
    case 'turn_meta':
      return ChatEvent.turnMeta(
        roleMode: json['role_mode'] as String?,
        analysis: json['analysis'] as String?,
        sceneId: json['scene_id'] as String?,
        sceneLabel: json['scene_label'] as String?,
        intention: json['intention'] as String?,
        currentGoal: json['current_goal'] as String?,
        behavior: json['behavior'] as String?,
        mode: json['mode'] as String?,
        actionIntent: json['action_intent'] as String?,
        // 无引用时字段缺省（非空数组）
        memoryRefs: json['memory_refs'] == null
            ? null
            : MemoryRefs(
                (json['memory_refs'] as List<dynamic>)
                    .map((e) => MemoryRef.fromJson(e as Map<String, dynamic>))
                    .toList(),
              ),
      );
    case 'token':
      return ChatEvent.token(delta: json['delta'] as String? ?? '');
    case 'tool_step':
      return ChatEvent.toolStep(
        stepId: json['step_id'] as String? ?? '',
        toolId: json['tool_id'] as String? ?? '',
        label: json['label'] as String? ?? '',
        status: json['status'] as String? ?? 'running',
        detail: json['detail'] as String?,
        target: json['target'] as String?,
      );
    case 'done':
      return const ChatEvent.done();
    case 'failure':
      return ChatEvent.failure(
        detail: json['detail'] as String?,
        error: json['error'] as String?,
      );
    default:
      throw FormatException('unregistered event type: $type');
  }
}
