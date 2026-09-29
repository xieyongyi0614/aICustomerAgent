import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/chat_history_repository.dart';
import '../data/chat_ledger_repository.dart';
import '../domain/chat_page_state.dart' show ChatMessageItem;

/// 本会话的记账记录：会话消息 + 月度摘要，全部取自服务端。
///
/// 设计稿 `21-chat-ledger` 的「过程卡」由流式 `tool_step` 事件驱动，该事件只在
/// 对话进行中经 sink 下发，既不落库也无读面，历史会话无法复原；因此本页只渲染
/// 可复现的真实数据，不合成过程步骤。
class ChatLedgerPage extends StatefulWidget {
  const ChatLedgerPage({super.key, this.conversationId, this.loader});

  final String? conversationId;

  /// 测试注入；生产走 [loadChatLedger]。
  final ChatLedgerLoader? loader;

  @override
  State<ChatLedgerPage> createState() => _ChatLedgerPageState();
}

class ChatLedgerData {
  const ChatLedgerData({required this.messages, this.summary});

  final List<ChatMessageItem> messages;
  final ChatLedgerSummary? summary;
}

typedef ChatLedgerLoader = Future<ChatLedgerData> Function(
  String conversationId,
);

Future<ChatLedgerData> loadChatLedger(String conversationId) async {
  final page = await ChatHistoryRemoteRepository().messages(conversationId);
  ChatLedgerSummary? summary;
  try {
    summary = await ChatLedgerRepository().fetchMonthSummary();
  } catch (_) {
    summary = null;
  }
  return ChatLedgerData(
    messages: page?.messages ?? const <ChatMessageItem>[],
    summary: summary,
  );
}

class _ChatLedgerPageState extends State<ChatLedgerPage> {
  ChatLedgerData? _data;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final id = widget.conversationId;
    if (id == null || id.isEmpty) {
      setState(() {
        _data = const ChatLedgerData(messages: <ChatMessageItem>[]);
        _failed = false;
      });
      return;
    }
    setState(() {
      _data = null;
      _failed = false;
    });
    try {
      final data = await (widget.loader ?? loadChatLedger)(id);
      if (!mounted) return;
      setState(() => _data = data);
    } catch (_) {
      if (!mounted) return;
      setState(() => _failed = true);
    }
  }

  void _back() {
    if (context.canPop()) {
      context.pop();
    } else {
      context.go('/chat');
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 10, 18, 6),
              child: Row(
                children: [
                  GestureDetector(
                    onTap: _back,
                    behavior: HitTestBehavior.opaque,
                    child: Row(
                      children: [
                        Icon(AppIcons.chevronLeft,
                            size: 18, color: colors.ink2),
                        const SizedBox(width: 2),
                        Text('返回对话',
                            style: type.sub.copyWith(color: colors.ink2)),
                      ],
                    ),
                  ),
                  const Spacer(),
                  Text('AI 记账', style: type.pageTitle),
                ],
              ),
            ),
            Expanded(child: _body(context)),
          ],
        ),
      ),
    );
  }

  Widget _body(BuildContext context) {
    if (_failed) {
      return ErrorState(onRetry: _load);
    }
    final data = _data;
    if (data == null) {
      return const LoadingState();
    }
    if (data.messages.isEmpty) {
      return EmptyState(
        message: '这个会话还没有记账记录',
        actionLabel: '去记一笔',
        onAction: () => context.go('/chat'),
      );
    }
    final colors = context.colors;
    final type = context.typography;
    return ListView(
      padding: const EdgeInsets.fromLTRB(18, 6, 18, 28),
      children: [
        const MemHint(text: '工具调用 · 记账 Skill'),
        const SizedBox(height: 14),
        for (final message in data.messages) ...[
          Align(
            alignment: message.role == 'user'
                ? Alignment.centerRight
                : Alignment.centerLeft,
            child: MessageBubble(
              text: message.content,
              isUser: message.role == 'user',
              enableMarkdown: message.role != 'user',
            ),
          ),
          const SizedBox(height: 12),
        ],
        if (data.summary != null) ...[
          const SizedBox(height: 4),
          AiCard(
            title: '本月记账',
            actionLabel: '查看账本 →',
            onAction: () => context.go('/ledger'),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Text(
                      '¥${data.summary!.expenseText}',
                      style: type
                          .numeric(type.display.copyWith(color: colors.ink)),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '支出 · ${data.summary!.entryCount} 笔',
                      style: type.sub.copyWith(color: colors.ink2),
                    ),
                  ],
                ),
                if (data.summary!.comparisonLabel != null) ...[
                  const SizedBox(height: 6),
                  Text(
                    data.summary!.comparisonLabel!,
                    style: type.caption.copyWith(color: colors.ink3),
                  ),
                ],
              ],
            ),
          ),
        ],
      ],
    );
  }
}
