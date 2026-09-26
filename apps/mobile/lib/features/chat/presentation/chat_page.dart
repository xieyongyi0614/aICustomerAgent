import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/state/persona_mode.dart';
import '../../../app/theme/theme_context.dart';
import '../../../core/analytics/analytics.dart';
import '../../../core/network/events/chat_event.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/components/components.dart';
import '../data/chat_history_repository.dart';
import '../data/chat_stream_repository.dart';
import '../domain/chat_page_state.dart';
import 'streaming/chat_stream_controller.dart';
import 'widgets/persona_status_bar.dart';

/// B2 #chat 八段装配（顺序固定）。
class ChatPage extends ConsumerStatefulWidget {
  const ChatPage({super.key});

  @override
  ConsumerState<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends ConsumerState<ChatPage> {
  final _scroll = ScrollController();
  final _input = TextEditingController();
  bool _stickToBottom = true;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
  }

  void _onScroll() {
    if (!_scroll.hasClients) return;
    final atBottom =
        _scroll.position.pixels >= _scroll.position.maxScrollExtent - 24;
    _stickToBottom = atBottom;
  }

  @override
  void dispose() {
    _scroll.dispose();
    _input.dispose();
    super.dispose();
  }

  void _maybeJumpToBottom() {
    if (!_stickToBottom || !_scroll.hasClients) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
  }

  void _openModeSheet() {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: context.colors.transparent,
      builder: (sheetContext) {
        return Container(
          padding: const EdgeInsets.fromLTRB(18, 20, 18, 32),
          decoration: BoxDecoration(
            gradient:
                Theme.of(sheetContext).extension<AppGradients>()!.deepPersona,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: ModeSelector(
            value: ref.read(personaModeProvider),
            onChanged: (m) {
              ref.read(personaModeProvider.notifier).set(m);
              Navigator.of(sheetContext).pop();
            },
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final state = ref.watch(chatPageStateProvider);
    _maybeJumpToBottom();

    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            PersonaStatusBar(
              mode: ref.watch(personaModeProvider),
              online: true,
              onBack: () => context.go('/home'),
              onOpenModeSheet: _openModeSheet,
            ),
            if (state.showMemoryHint)
              Padding(
                padding: const EdgeInsets.fromLTRB(18, 8, 18, 8),
                child: MemHint(text: state.memoryHintText),
              ),
            Expanded(child: _body(state)),
            SafeArea(
              top: false,
              child: ChatInputBar(
                controller: _input,
                onSend: () {
                  final text = _input.text.trim();
                  if (text.isEmpty) return;
                  _input.clear();
                  ref.read(chatPageStateProvider.notifier).send(text);
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _body(ChatPageState state) {
    if (state.loading) {
      return ListView(
        children: const [
          SkeletonCard(),
          SkeletonCard(),
          SkeletonCard(),
        ],
      );
    }
    if (state.error != null && state.messages.isEmpty) {
      return ErrorState(
        message: state.error is String
            ? state.error! as String
            : StateCopy.serverError,
        onRetry: () => ref.read(chatPageStateProvider.notifier).reload(),
      );
    }
    if (state.messages.isEmpty && state.streamingText.isEmpty) {
      return const EmptyState(message: '和亚丝娜说句话吧');
    }
    return ListView(
      controller: _scroll,
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
      children: [
        for (final m in state.messages)
          MessageBubble(
            text: m.content,
            isUser: m.role == 'human',
            enableMarkdown: m.role != 'human',
          ),
        if (state.toolSteps.isNotEmpty)
          ProcCard(
            title: '正在为你记账',
            steps: [
              for (final s in state.toolSteps)
                ProcStep(
                  label: s.label,
                  status: s.status,
                  detail: s.detail,
                  target: s.target,
                ),
            ],
          ),
        if (state.streamingText.isNotEmpty)
          MessageBubble.streaming(
            text: state.streamingText,
          ),
        if (state.streaming)
          const Padding(
            padding: EdgeInsets.only(left: 30, top: 4),
            child: Align(
              alignment: Alignment.centerLeft,
              child: TypingIndicator(),
            ),
          ),
        if (state.error != null && state.messages.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(left: 30, top: 8, right: 18),
            child: _InlineStreamError(
              message: state.error is String
                  ? state.error! as String
                  : StateCopy.streamInterrupted,
              onRetry: state.lastUserText == null
                  ? null
                  : () => ref
                      .read(chatPageStateProvider.notifier)
                      .send(state.lastUserText!),
            ),
          ),
        const SizedBox(height: 12),
      ],
    );
  }
}

final chatPageStateProvider =
    NotifierProvider<ChatPageNotifier, ChatPageState>(ChatPageNotifier.new);

class ChatPageNotifier extends Notifier<ChatPageState> {
  ChatStreamRepository? _repo;
  ChatStreamController? _controller;
  ChatHistoryRemoteRepository? _historyRepo;
  bool _disposed = false;

  @override
  ChatPageState build() {
    ref.onDispose(() {
      _disposed = true;
      _controller?.dispose();
      _repo?.dispose();
    });
    unawaited(_loadHistory());
    return const ChatPageState(loading: true);
  }

  /// 进入页面恢复上次会话：优先用持久化的会话 id 拉取，
  /// 缺失（首次使用 / 清过数据）时回退到服务端最新会话。
  Future<void> _loadHistory() async {
    try {
      final prefs = await PrefsStore.load();
      if (_disposed) return;
      final historyRepo = _historyRepo ??= ChatHistoryRemoteRepository();
      final cachedId = prefs.lastConversationId();
      var page = cachedId == null ? null : await historyRepo.messages(cachedId);
      if (_disposed) return;
      page ??= await historyRepo.latest();
      if (_disposed) return;
      if (page != null) {
        await prefs.setLastConversationId(page.conversationId);
        if (_disposed) return;
        state = state.copyWith(
          loading: false,
          currentSessionId: page.conversationId,
          messages: page.messages,
        );
        return;
      }
    } catch (_) {
      // 历史不可达时不阻塞新对话：保持空态可正常发送，发送链路自会暴露错误。
    } finally {
      if (!_disposed && state.loading) {
        state = state.copyWith(loading: false);
      }
    }
  }

  Future<void> reload() async {
    state = state.copyWith(loading: true, error: null);
    await Future<void>.delayed(const Duration(milliseconds: 30));
    state = state.copyWith(loading: false);
  }

  void applyMemoryRefs(List<MemoryRef> refs) {
    state = state.copyWith(memoryRefs: refs);
  }

  Future<void> send(String text) async {
    Analytics.track('chat_send');
    final repo = _repo ??= ChatStreamRepository();
    final prefs = await PrefsStore.load();
    final userMsg = ChatMessageItem(
      id: 'local_${DateTime.now().millisecondsSinceEpoch}',
      role: 'human',
      content: text,
      createdAt: DateTime.now(),
    );
    state = state.copyWith(
      messages: [...state.messages, userMsg],
      streamingText: '',
      toolSteps: const [],
      memoryRefs: const [],
      loading: false,
      error: null,
      lastUserText: text,
    );
    _controller?.dispose();
    final controller = ChatStreamController(
      onState: (turnState) {
        state = state.copyWith(
          streamingText: turnState.text,
          toolSteps: turnState.toolSteps,
          memoryRefs: turnState.memoryRefs,
        );
      },
    )..attachCancel(repo.cancel);
    _controller = controller;
    try {
      await controller.consume(repo.send(
        content: text,
        sessionId: state.currentSessionId,
        onSessionId: (sessionId) {
          if (!_disposed) state = state.copyWith(currentSessionId: sessionId);
          unawaited(prefs.setLastConversationId(sessionId));
        },
      ));
      final doneText = controller.state.text;
      if (doneText.isNotEmpty) {
        state = state.copyWith(
          streamingText: '',
          messages: [
            ...state.messages,
            ChatMessageItem(
              id: 'ai_${DateTime.now().millisecondsSinceEpoch}',
              role: 'ai',
              content: doneText,
              createdAt: DateTime.now(),
            ),
          ],
        );
      }
      if (controller.state.incomplete) {
        state = state.copyWith(
          error: controller.state.error?.userMessage ?? StateCopy.streamInterrupted,
        );
      }
    } catch (e) {
      state = state.copyWith(error: e, streamingText: '');
    }
  }
}

class _InlineStreamError extends StatelessWidget {
  const _InlineStreamError({required this.message, this.onRetry});

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = Theme.of(context).extension<AppTypography>()!;
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 12, 12),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: colors.line),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              message,
              style: type.body.copyWith(fontSize: 13.5, color: colors.ink2),
            ),
          ),
          if (onRetry != null)
            TextButton(
              onPressed: onRetry,
              child: const Text(StateCopy.retryAction),
            ),
        ],
      ),
    );
  }
}
