import 'dart:convert';

import 'chat_event.dart';

/// NDJSON 行 → ChatEvent。
///
/// 判别契约（与 API-002 冻结 wire 对齐）：
/// - `turn_meta` / `tool_step`：带 `type` 字段
/// - `token`：`{"delta": ...}`（无 `type`）
/// - `done`：`{"done": true, ...}`（无 `type`）
/// - `failure`：`{"detail"/"error": ...}`（无 `type`）
/// 未知形态 fail-closed（FormatException）。
ChatEvent parseChatEvent(Map<String, dynamic> json) {
  final type = json['type'] as String?;
  if (type != null) {
    switch (type) {
      case 'turn_meta':
        return _parseTurnMeta(json);
      case 'tool_step':
        return ChatEvent.toolStep(
          stepId: json['step_id'] as String? ?? '',
          toolId: json['tool_id'] as String? ?? '',
          label: json['label'] as String? ?? '',
          status: json['status'] as String? ?? 'running',
          detail: json['detail'] as String?,
          target: json['target'] as String?,
        );
      default:
        throw FormatException('unregistered event type: $type');
    }
  }
  if (json.containsKey('delta')) {
    return ChatEvent.token(delta: json['delta'] as String? ?? '');
  }
  if (json['done'] == true) {
    return const ChatEvent.done();
  }
  if (json.containsKey('detail') || json.containsKey('error')) {
    return ChatEvent.failure(
      detail: json['detail'] as String?,
      error: json['error'] is String
          ? json['error'] as String
          : json['error'] == null
              ? null
              : jsonEncode(json['error']),
    );
  }
  throw FormatException('unregistered event: $json');
}

ChatEvent _parseTurnMeta(Map<String, dynamic> json) {
  return ChatEvent.turnMeta(
    roleMode: _asDisplayString(json['role_mode'], keys: const ['mode', 'label']),
    analysis: _asDisplayString(json['analysis'], keys: const ['summary', 'label']),
    sceneId: _asDisplayString(json['scene_id'] ?? json['scene_intent'], keys: const ['intent', 'id']),
    sceneLabel: _asDisplayString(json['scene_label'] ?? json['scene_state'], keys: const ['label', 'state']),
    intention: _asDisplayString(json['intention'], keys: const ['type', 'intention', 'label']),
    currentGoal: _asDisplayString(json['current_goal'], keys: const ['description', 'id', 'label']),
    behavior: _asDisplayString(json['behavior'], keys: const ['strategy', 'label']),
    mode: _asDisplayString(json['mode'], keys: const ['effective', 'confirmed', 'mode']),
    actionIntent: _asDisplayString(json['action_intent'], keys: const ['type', 'action', 'label']),
    memoryRefs: json['memory_refs'] == null
        ? null
        : MemoryRefs(
            (json['memory_refs'] as List<dynamic>)
                .map((e) => MemoryRef.fromJson(e as Map<String, dynamic>))
                .toList(),
          ),
  );
}

/// turn_meta 的 role_mode / analysis 等在 wire 上是对象；模型侧保留展示字符串。
String? _asDisplayString(Object? value, {List<String> keys = const []}) {
  if (value == null) return null;
  if (value is String) return value;
  if (value is Map) {
    for (final key in keys) {
      final v = value[key];
      if (v is String && v.isNotEmpty) return v;
    }
    return null;
  }
  return value.toString();
}
