import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

import '../tokens/tokens.dart';
import '../orb/orb.dart';
import 'incremental_markdown.dart';

MarkdownStyleSheet _markdownSheet(
  TextStyle textStyle,
  AppColors colors,
  AppRadii radii,
) {
  return MarkdownStyleSheet(
    p: textStyle,
    h1: textStyle.copyWith(fontSize: 18, fontWeight: FontWeight.w700),
    h2: textStyle.copyWith(fontSize: 16.5, fontWeight: FontWeight.w700),
    h3: textStyle.copyWith(fontSize: 15, fontWeight: FontWeight.w700),
    list: textStyle,
    code: textStyle.copyWith(
      fontFamily: 'monospace',
      fontSize: 12.5,
      backgroundColor: colors.fillSubtle,
    ),
    codeblockDecoration: BoxDecoration(
      color: colors.fillSubtle,
      borderRadius: radii.rMd,
    ),
    blockquote: textStyle.copyWith(color: colors.ink2),
  );
}

/// A13 消息气泡：用户右深色泡 / AI 左白卡 + 迷你 Orb sm。
/// AI 侧走增量 Markdown（已闭合块完整渲染，尾部未闭合按纯文本）。
class MessageBubble extends StatelessWidget {
  const MessageBubble({
    super.key,
    required this.text,
    required this.isUser,
    this.enableMarkdown = false,
    this.streaming = false,
  });

  final String text;
  final bool isUser;
  final bool enableMarkdown;
  final bool streaming;

  const MessageBubble.streaming({
    super.key,
    required this.text,
  })  : isUser = false,
        enableMarkdown = true,
        streaming = true;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final textStyle = type.body.copyWith(
      fontSize: 14.5,
      height: 1.65,
      color: isUser ? colors.userBubbleText : colors.bodyOnBubble,
    );
    final Widget body;
    if (!isUser && enableMarkdown) {
      final (closed, openTail) = streaming
          ? const IncrementalMarkdown().split(text)
          : (text, '');
      body = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (closed.isNotEmpty)
            MarkdownBody(
              data: closed,
              selectable: true,
              styleSheet: _markdownSheet(textStyle, colors, radii),
            ),
          if (openTail.isNotEmpty)
            Text(openTail, style: textStyle),
        ],
      );
    } else {
      body = Text(text, style: textStyle);
    }
    final bubble = Container(
      padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 15),
      constraints: const BoxConstraints(maxWidth: 280),
      decoration: BoxDecoration(
        color: isUser ? colors.userBubbleBg : colors.surface,
        borderRadius: BorderRadius.only(
          topLeft: const Radius.circular(20),
          topRight: const Radius.circular(20),
          bottomLeft: Radius.circular(isUser ? 20 : radii.bubbleTail),
          bottomRight: Radius.circular(isUser ? radii.bubbleTail : 20),
        ),
      ),
      child: body,
    );

    if (isUser) {
      return Align(
        alignment: Alignment.centerRight,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: bubble,
        ),
      );
    }
    return Align(
      alignment: Alignment.centerLeft,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          mainAxisSize: MainAxisSize.min,
          children: [
            const Orb(size: OrbSize.sm),
            const SizedBox(width: 8),
            Flexible(child: bubble),
          ],
        ),
      ),
    );
  }
}

/// A15 typing 三点指示器（1.1s 循环，动效纪律显式例外）。
class TypingIndicator extends StatefulWidget {
  const TypingIndicator({super.key});

  @override
  State<TypingIndicator> createState() => _TypingIndicatorState();
}

class _TypingIndicatorState extends State<TypingIndicator>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  )..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        return Row(
          mainAxisSize: MainAxisSize.min,
          children: List.generate(3, (i) {
            final t = (_c.value - i * 0.16) % 1.0;
            final wave = Curves.easeInOut.transform(t.clamp(0, 1));
            return Padding(
              padding: const EdgeInsets.symmetric(horizontal: 3),
              child: Opacity(
                opacity: 0.35 + 0.65 * wave,
                child: Transform.translate(
                  offset: Offset(0, -3 * wave),
                  child: Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: colors.tagPreferenceFg,
                      shape: BoxShape.circle,
                    ),
                  ),
                ),
              ),
            );
          }),
        );
      },
    );
  }
}

/// A16 对话输入栏：加号 / 语音（P2 只留位）/ 发送。
class ChatInputBar extends StatelessWidget {
  const ChatInputBar({
    super.key,
    this.hint = '继续说点什么…例如「午饭 35 元」',
    this.onSend,
    this.controller,
  });

  final String hint;
  final VoidCallback? onSend;
  final TextEditingController? controller;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    final gradients = Theme.of(context).extension<AppGradients>()!;
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 26),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [colors.transparent, colors.canvas],
        ),
      ),
      child: Container(
        padding: const EdgeInsets.fromLTRB(16, 7, 7, 7),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radii.rFull,
          boxShadow: elevation.card,
        ),
        child: Row(
          children: [
            _IconCircle(icon: Icons.add, color: colors.ink2, onTap: null),
            const SizedBox(width: 8),
            Expanded(
              child: TextField(
                controller: controller,
                decoration: InputDecoration(
                  hintText: hint,
                  hintStyle: type.body.copyWith(color: colors.ink3),
                  border: InputBorder.none,
                  isDense: true,
                ),
              ),
            ),
            // 语音 P2：只留位置，零实现
            _IconCircle(icon: Icons.mic_none, color: colors.ink3, onTap: null),
            const SizedBox(width: 6),
            GestureDetector(
              onTap: onSend,
              child: Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: gradients.ai,
                ),
                child: Icon(Icons.arrow_upward,
                    size: 17, color: colors.onDeepPrimary),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _IconCircle extends StatelessWidget {
  const _IconCircle({
    required this.icon,
    required this.color,
    this.onTap,
  });

  final IconData icon;
  final Color color;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: SizedBox(
        width: 34,
        height: 34,
        child: Icon(icon, size: 20, color: color),
      ),
    );
  }
}
