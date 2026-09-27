import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/orb/orb.dart';
import 'widgets/agreement_check.dart';

/// 设计稿 ⓪ 登录 / 初见 Onboarding（邮箱优先）：登录即「与亚丝娜的第一天」。
class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  static final _emailPattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

  final _email = TextEditingController();
  bool _agreed = true;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  void _notice(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        behavior: SnackBarBehavior.floating,
        content: Text(message),
      ),
    );
  }

  bool get _agreementAccepted {
    if (_agreed) return true;
    _notice('请先阅读并同意《用户协议》和《隐私政策》');
    return false;
  }

  void _onEmailLogin() {
    FocusScope.of(context).unfocus();
    if (!_agreementAccepted) return;
    final email = _email.text.trim();
    if (!_emailPattern.hasMatch(email)) {
      _notice('请输入正确的邮箱地址');
      return;
    }
    context.push('/verify', extra: email);
  }

  void _onWeChatLogin() {
    if (!_agreementAccepted) return;
    _notice('微信登录还没接入，先用邮箱见亚丝娜吧');
  }

  void _onPhoneLogin() {
    if (!_agreementAccepted) return;
    _notice('手机号登录还没接入，先用邮箱吧');
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      // 键盘弹出不重排布局：Spacer 底部锚定 + 视口逐帧收缩会叠加出上挪与抖动
      resizeToAvoidBottomInset: false,
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
                    // 辉光半径到球心约 98px，超出 160 盘面，不可裁剪
                    clipBehavior: Clip.none,
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
                  borderRadius: context.radii.rLg,
                  boxShadow: context.elevation.card,
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
              const SizedBox(height: 24),
              const Spacer(),
              _EmailField(controller: _email, onSubmit: _onEmailLogin),
              const SizedBox(height: 12),
              _EmailLoginButton(onTap: _onEmailLogin),
              const SizedBox(height: 10),
              Text(
                '未注册的邮箱将自动创建账号',
                textAlign: TextAlign.center,
                style: type.sub.copyWith(
                  fontSize: 11.5,
                  color: colors.ink3,
                ),
              ),
              const SizedBox(height: 10),
              const _AltDivider(),
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _AltLogin(
                    label: '微信',
                    icon: _WeChatGlyph(size: 23, inverted: true),
                    onTap: _onWeChatLogin,
                  ),
                  const SizedBox(width: 46),
                  _AltLogin(
                    label: '手机号',
                    icon: Icon(AppIcons.smartphone,
                        size: 23, color: colors.ink2),
                    onTap: _onPhoneLogin,
                  ),
                ],
              ),
              const SizedBox(height: 10),
              AgreementCheck(
                checked: _agreed,
                onToggle: () => setState(() => _agreed = !_agreed),
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

class _EmailField extends StatelessWidget {
  const _EmailField({required this.controller, required this.onSubmit});

  final TextEditingController controller;
  final VoidCallback onSubmit;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Container(
      height: 52,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: context.radii.rFull,
        boxShadow: context.elevation.pill,
      ),
      child: Row(
        children: [
          Icon(AppIcons.mail, size: 18, color: colors.aiPrimary),
          const SizedBox(width: 10),
          Expanded(
            child: TextField(
              controller: controller,
              keyboardType: TextInputType.emailAddress,
              textInputAction: TextInputAction.done,
              onSubmitted: (_) => onSubmit(),
              autofillHints: const [AutofillHints.email],
              style: type.body.copyWith(fontSize: 15, color: colors.ink),
              decoration: InputDecoration(
                hintText: '输入邮箱地址',
                hintStyle:
                    type.body.copyWith(fontSize: 15, color: colors.ink3),
                border: InputBorder.none,
                isCollapsed: true,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _EmailLoginButton extends StatelessWidget {
  const _EmailLoginButton({required this.onTap});

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 15),
        decoration: BoxDecoration(
          gradient: context.gradients.ai,
          borderRadius: radii.rFull,
          boxShadow: context.elevation.btnPrimary,
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(
              '邮箱登录 / 注册',
              style: type.rowTitle.copyWith(
                fontSize: 15,
                fontWeight: FontWeight.w700,
                color: colors.onDeepPrimary,
              ),
            ),
            const SizedBox(width: 9),
            Icon(AppIcons.arrowRight,
                size: 19, color: colors.onDeepPrimary),
          ],
        ),
      ),
    );
  }
}

class _AltDivider extends StatelessWidget {
  const _AltDivider();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      children: [
        Expanded(child: Container(height: 1, color: colors.line)),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12),
          child: Text(
            '其他登录方式',
            style: type.sub.copyWith(
              fontSize: 11.5,
              letterSpacing: 1,
              color: colors.ink3,
            ),
          ),
        ),
        Expanded(child: Container(height: 1, color: colors.line)),
      ],
    );
  }
}

class _AltLogin extends StatelessWidget {
  const _AltLogin({
    required this.label,
    required this.icon,
    required this.onTap,
  });

  final String label;
  final Widget icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Column(
        children: [
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: colors.surface,
              border: Border.all(color: colors.line, width: 1.5),
              boxShadow: context.elevation.card,
            ),
            child: Center(child: icon),
          ),
          const SizedBox(height: 7),
          Text(
            label,
            style: type.sub.copyWith(fontSize: 11.5, color: colors.ink2),
          ),
        ],
      ),
    );
  }
}

class _WeChatGlyph extends StatelessWidget {
  const _WeChatGlyph({required this.size, this.inverted = false});

  final double size;

  /// true = 绿色图形（用于白底圆形按钮）；false = 白色图形（用于绿色大按钮）。
  final bool inverted;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return CustomPaint(
      size: Size.square(size),
      painter: _WeChatGlyphPainter(
        body: inverted ? colors.wechat : colors.onDeepPrimary,
        detail: inverted ? colors.surface : colors.wechat,
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
