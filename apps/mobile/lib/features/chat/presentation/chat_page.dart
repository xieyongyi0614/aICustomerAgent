import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/network/events/chat_event.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';
import '../domain/chat_page_state.dart';

/// B2 #chat 八段装配（顺序固定）。
/// 头部/气泡/输入栏/过程卡为槽位，细节归 APP-011/012/013。
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
            // 1 头部人格状态栏（槽位 → APP-012）
            const _HeaderSlot(),
            if (state.showMemoryHint)
              Padding(
                padding: const EdgeInsets.fromLTRB(18, 8, 18, 8),
                child: MemHint(text: state.memoryHintText),
              ),
            Expanded(child: _body(state)),
            // 8 输入栏（A16），bottom 88 在布局层让出
            Padding(
              padding: const EdgeInsets.only(bottom: 88),
              child: ChatInputBar(
                onSend: () {},
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
        // 工具过程卡穿插位（APP-013）
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
        // 建议 chips 穿插位（APP-013）
      ],
    );
  }
}

class _HeaderSlot extends StatelessWidget {
  const _HeaderSlot();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 12, 18, 8),
      child: Row(
        children: [
          const Orb(size: OrbSize.md),
          const SizedBox(width: 10),
          Text('亚丝娜', style: type.sectionTitle.copyWith(color: colors.ink)),
          const SizedBox(width: 8),
          ModeChip(label: 'Default 模式 · 长期记忆运行中'),
        ],
      ),
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
}
