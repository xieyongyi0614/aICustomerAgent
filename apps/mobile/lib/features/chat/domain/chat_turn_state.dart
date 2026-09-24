import '../../../core/network/errors/app_error.dart';
import '../../../core/network/events/chat_event.dart';

enum ChatTurnStatus { idle, streaming, toolRunning, done, failed }

class ChatToolStep {
  const ChatToolStep({
    required this.stepId,
    required this.toolId,
    required this.label,
    required this.status,
    this.detail,
    this.target,
  });

  final String stepId;
  final String toolId;
  final String label;
  final String status;
  final String? detail;
  final String? target;

  ChatToolStep copyWith({String? status, String? detail, String? target}) =>
      ChatToolStep(
        stepId: stepId,
        toolId: toolId,
        label: label,
        status: status ?? this.status,
        detail: detail ?? this.detail,
        target: target ?? this.target,
      );
}

/// 对话轮状态机：唯一状态真相。
class ChatTurnState {
  const ChatTurnState({
    this.status = ChatTurnStatus.idle,
    this.text = '',
    this.memoryRefs = const [],
    this.toolSteps = const [],
    this.incomplete = false,
    this.canRetry = false,
    this.error,
  });

  final ChatTurnStatus status;
  final String text;
  final List<MemoryRef> memoryRefs;
  final List<ChatToolStep> toolSteps;

  /// done 未到即结束 → true，允许重试，不得静默当正常结束
  final bool incomplete;
  final bool canRetry;
  final AppError? error;

  ChatTurnState copyWith({
    ChatTurnStatus? status,
    String? text,
    List<MemoryRef>? memoryRefs,
    List<ChatToolStep>? toolSteps,
    bool? incomplete,
    bool? canRetry,
    AppError? error,
  }) {
    return ChatTurnState(
      status: status ?? this.status,
      text: text ?? this.text,
      memoryRefs: memoryRefs ?? this.memoryRefs,
      toolSteps: toolSteps ?? this.toolSteps,
      incomplete: incomplete ?? this.incomplete,
      canRetry: canRetry ?? this.canRetry,
      error: error ?? this.error,
    );
  }
}

/// ChatEvent → ChatTurnState 纯迁移。
ChatTurnState reduceChatEvent(ChatTurnState state, ChatEvent event) {
  return switch (event) {
    TurnMeta(:final memoryRefs) => state.copyWith(
        status: ChatTurnStatus.streaming,
        memoryRefs: memoryRefs?.items ?? state.memoryRefs,
      ),
    TokenDelta(:final delta) => state.copyWith(
        status: ChatTurnStatus.streaming,
        text: state.text + delta,
      ),
    ToolStep(
      :final stepId,
      :final toolId,
      :final label,
      :final status,
      :final detail,
      :final target,
    ) =>
      _upsertToolStep(
        state,
        ChatToolStep(
          stepId: stepId,
          toolId: toolId,
          label: label,
          status: status,
          detail: detail,
          target: target,
        ),
      ),
    Done() => state.copyWith(status: ChatTurnStatus.done, canRetry: false),
    Failure(:final detail, :final error) => state.copyWith(
        status: ChatTurnStatus.failed,
        canRetry: true,
        error: AppError.streamInterrupted([detail, error].whereType<String>().join(' ')),
      ),
  };
}

ChatTurnState _upsertToolStep(ChatTurnState state, ChatToolStep step) {
  final steps = [...state.toolSteps];
  final i = steps.indexWhere((e) => e.stepId == step.stepId);
  if (i >= 0) {
    steps[i] = steps[i].copyWith(
      status: step.status,
      detail: step.detail,
      target: step.target,
    );
  } else {
    steps.add(step);
  }
  final anyRunning = steps.any((e) => e.status == 'running');
  return state.copyWith(
    toolSteps: steps,
    status: anyRunning ? ChatTurnStatus.toolRunning : state.status,
  );
}

/// 断流：done 未到。
ChatTurnState markIncomplete(ChatTurnState state) {
  if (state.status == ChatTurnStatus.done || state.status == ChatTurnStatus.failed) {
    return state;
  }
  return state.copyWith(
    status: ChatTurnStatus.failed,
    incomplete: true,
    canRetry: true,
    error: AppError.streamInterrupted(),
  );
}
