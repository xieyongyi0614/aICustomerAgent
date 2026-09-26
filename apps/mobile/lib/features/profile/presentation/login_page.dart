import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/orb/orb.dart';
import 'widgets/agreement_check.dart';

/// 设计稿 ⓪ 登录 / 初见 Onboarding：登录即「与亚丝娜的第一天」。
class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  bool _agreed = true;

  void _noticeWeChatUnavailable() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        behavior: SnackBarBehavior.floating,
        content: Text('微信登录还没接入，先用手机号见亚丝娜吧'),
      ),
    );
  }

  Future<void> _enterAsGuest() async {
    final prefs = await PrefsStore.load();
    await prefs.markLoginSeen();
    if (!mounted) return;
    context.go('/home');
  }

  void _onWeChatLogin() {
    if (!_agreed) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          behavior: SnackBarBehavior.floating,
          content: Text('请先阅读并同意《用户协议》和《隐私政策》'),
        ),
      );
      return;
    }
    _noticeWeChatUnavailable();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    final elevation = context.elevation;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            child: ConstrainedBox(
              constraints:
                  BoxConstraints(minHeight: constraints.maxHeight),
              child: IntrinsicHeight(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 30),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
              const SizedBox(height: 48),
              Center(
                child: SizedBox(
                  width: 160,
                  height: 160,
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      DecoratedBox(
                        decoration: BoxDecoration(
                          gradient: context.gradients.orbHalo,
                          shape: BoxShape.circle,
                        ),
                        child: const SizedBox(width: 160, height: 160),
                      ),
                      const Orb(size: OrbSize.lg),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 30),
              Padding(
                padding: const EdgeInsets.only(left: 10),
                child: Text(
                  '朝夕',
                  textAlign: TextAlign.center,
                  style: type.display.copyWith(
                    fontSize: 34,
                    fontWeight: FontWeight.w800,
                    letterSpacing: 10,
                    color: colors.ink,
                  ),
                ),
              ),
              const SizedBox(height: 10),
              Text(
                '一个有长期记忆的 AI 生命管家',
                textAlign: TextAlign.center,
                style: type.sub.copyWith(
                  fontSize: 13.5,
                  letterSpacing: 0.7,
                  color: colors.ink2,
                ),
              ),
              const SizedBox(height: 36),
              Container(
                padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
                decoration: BoxDecoration(
                  color: colors.surface,
                  borderRadius: radii.rLg,
                  boxShadow: elevation.card,
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Orb(size: OrbSize.sm),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        '你好，我是亚丝娜。\n登录之后，我会记住你、理解你，\n陪你把每一天过好。',
                        style: type.body.copyWith(
                          fontSize: 13.5,
                          height: 1.8,
                          color: colors.bodyOnCard,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const Spacer(),
              _PrimaryAction(
                label: '微信一键登录',
                onTap: _onWeChatLogin,
                background: colors.wechat,
                foreground: colors.onDeepPrimary,
                boxShadow: elevation.btnWechat,
                icon: const _WeChatGlyph(size: 20),
              ),
              const SizedBox(height: 12),
              _PrimaryAction(
                label: '手机号登录 / 注册',
                onTap: () => context.push('/verify'),
                background: colors.surface,
                foreground: colors.ink,
                boxShadow: elevation.card,
                border: Border.all(color: colors.line, width: 1.5),
                icon: Icon(AppIcons.smartphone,
                    size: 20, color: colors.onWhitePill),
              ),
              const SizedBox(height: 4),
              AgreementCheck(
                checked: _agreed,
                onToggle: () => setState(() => _agreed = !_agreed),
              ),
              const SizedBox(height: 15),
              GestureDetector(
                onTap: _enterAsGuest,
                behavior: HitTestBehavior.opaque,
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Text(
                    '先逛逛，稍后再登录 →',
                    textAlign: TextAlign.center,
                    style: type.sub.copyWith(
                      fontSize: 12.5,
                      color: colors.ink3,
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 20),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _PrimaryAction extends StatelessWidget {
  const _PrimaryAction({
    required this.label,
    required this.onTap,
    required this.background,
    required this.foreground,
    required this.boxShadow,
    required this.icon,
    this.border,
  });

  final String label;
  final VoidCallback onTap;
  final Color background;
  final Color foreground;
  final List<BoxShadow> boxShadow;
  final Widget icon;
  final Border? border;

  @override
  Widget build(BuildContext context) {
    final type = context.typography;
    final radii = context.radii;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 15),
        decoration: BoxDecoration(
          color: background,
          borderRadius: radii.rFull,
          boxShadow: boxShadow,
          border: border,
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            icon,
            const SizedBox(width: 9),
            Text(
              label,
              style: type.rowTitle.copyWith(
                fontSize: 15,
                fontWeight: FontWeight.w700,
                color: foreground,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _WeChatGlyph extends StatelessWidget {
  const _WeChatGlyph({required this.size});

  final double size;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return CustomPaint(
      size: Size.square(size),
      painter: _WeChatGlyphPainter(
        body: colors.onDeepPrimary,
        detail: colors.wechat,
      ),
    );
  }
}

class _WeChatGlyphPainter extends CustomPainter {
  const _WeChatGlyphPainter({required this.body, required this.detail});

  final Color body;
  final Color detail;

  @override
  void paint(Canvas canvas, Size size) {
    final scale = size.width / 24;
    canvas.scale(scale);
    final fill = Paint()..color = body;
    final hole = Paint()..color = detail;

    final bigBubble = Path()
      ..addOval(Rect.fromCircle(center: const Offset(9.2, 9.2), radius: 7.1))
      ..moveTo(5.2, 14.6)
      ..lineTo(2.4, 17.8)
      ..lineTo(7.2, 15.9)
      ..close();
    canvas.drawPath(bigBubble, fill);
    canvas.drawCircle(const Offset(6.3, 8.2), 1.05, hole);
    canvas.drawCircle(const Offset(11.6, 8.2), 1.05, hole);

    final smallBubble = Path()
      ..addOval(Rect.fromCircle(
          center: const Offset(15.7, 14.3), radius: 5.3));
    canvas.drawPath(smallBubble, fill);
    canvas.drawCircle(const Offset(13.9, 13.6), 0.85, hole);
    canvas.drawCircle(const Offset(17.6, 13.6), 0.85, hole);
    final tail = Path()
      ..moveTo(18.4, 18.2)
      ..lineTo(20.3, 20.6)
      ..lineTo(16.6, 19.2)
      ..close();
    canvas.drawPath(tail, fill);
  }

  @override
  bool shouldRepaint(covariant _WeChatGlyphPainter oldDelegate) =>
      oldDelegate.body != body || oldDelegate.detail != detail;
}
