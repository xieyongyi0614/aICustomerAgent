import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/network/events/chat_event.dart';
import '../../../design_system/components/components.dart';
import '../domain/chat_page_state.dart';
import 'widgets/persona_status_bar.dart';

/// B2 #chat 八段装配（顺序固定）。
class ChatPage extends ConsumerStatefulWidget {
  const ChatPage({super.key});

  @override
  ConsumerState<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends ConsumerState<ChatPage> {
  final _scroll = ScrollController();
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
            gradient: Theme.of(sheetContext).extension<AppGradients>()!.deepPersona,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
          ),
          child: ModeSelector(
            value: ref.read(chatPageStateProvider).mode,
            onChanged: (m) {
              ref.read(chatPageStateProvider.notifier).setPreferredMode(m);
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
              mode: state.mode,
              online: true,
              onOpenModeSheet: _openModeSheet,
            ),
            if (state.showMemoryHint)
              Padding(
                padding: const EdgeInsets.fromLTRB(18, 8, 18, 8),
                child: MemHint(text: state.memoryHintText),
              ),
            Expanded(child: _body(state)),
            Padding(
              padding: const EdgeInsets.only(bottom: 88),
              child: ChatInputBar(onSend: () {}),
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
    if (state.error != null) {
      return ErrorState(
        message: StateCopy.serverError,
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
          MessageBubble(text: m.content, isUser: m.role == 'human'),
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
          MessageBubble(text: state.streamingText, isUser: false),
        if (state.streaming)
          const Padding(
            padding: EdgeInsets.only(left: 30, top: 4),
            child: Align(
              alignment: Alignment.centerLeft,
              child: TypingIndicator(),
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
  @override
  ChatPageState build() => const ChatPageState(loading: true);

  Future<void> reload() async {
    state = state.copyWith(loading: true, error: null);
    await Future<void>.delayed(const Duration(milliseconds: 30));
    state = state.copyWith(loading: false);
  }

  void applyMemoryRefs(List<MemoryRef> refs) {
    state = state.copyWith(memoryRefs: refs);
  }

  /// 仅记录端上期望模式；写路径缺口见 APP-012 D4，不得伪造 role_mode。
  void setPreferredMode(RoleMode mode) {
    state = state.copyWith(mode: mode);
  }
}
