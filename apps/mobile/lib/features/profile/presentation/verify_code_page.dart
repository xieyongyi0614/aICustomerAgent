import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';
import '../data/auth_repository.dart';
import 'widgets/agreement_check.dart';

/// 设计稿 ⓪ 邮箱验证码：自动注册 + 称呼设置（称呼是亚丝娜的第一条记忆）。
/// 进入页面即请求发送验证码；验证通过换取长期令牌后进入首页。
class VerifyCodePage extends StatefulWidget {
  const VerifyCodePage({super.key, this.email, this.authRepository});

  /// 登录页带入的邮箱地址，用于「已发送至」展示（脱敏）。
  final String? email;

  final AuthRepository? authRepository;

  @override
  State<VerifyCodePage> createState() => _VerifyCodePageState();
}

class _VerifyCodePageState extends State<VerifyCodePage> {
  static const _resendSeconds = 60;
  static final _codePattern = RegExp(r'^\d{6}$');

  final _code = TextEditingController();
  final _codeFocus = FocusNode();
  final _nickname = TextEditingController();
  late final AuthRepository _repo =
      widget.authRepository ?? AuthRepository();
  Timer? _resendTimer;
  int _countdown = _resendSeconds;
  bool _agreed = true;
  bool _sending = false;
  bool _verifying = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _startCountdown();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _sendCode(initial: true);
    });
  }

  @override
  void dispose() {
    _code.dispose();
    _codeFocus.dispose();
    _nickname.dispose();
    _resendTimer?.cancel();
    super.dispose();
  }

  String get _maskedEmail {
    final email = widget.email?.trim() ?? '';
    if (email.isEmpty) return '你的邮箱';
    final at = email.indexOf('@');
    if (at <= 0) return email;
    final localHead =
        email.substring(0, at < 3 ? at : 3);
    return '$localHead***${email.substring(at)}';
  }

  void _notice(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        behavior: SnackBarBehavior.floating,
        content: Text(message),
      ),
    );
  }

  void _startCountdown({int seconds = _resendSeconds}) {
    _resendTimer?.cancel();
    setState(() => _countdown = seconds);
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (_countdown <= 1) {
        timer.cancel();
        if (mounted) setState(() => _countdown = 0);
        return;
      }
      if (mounted) setState(() => _countdown -= 1);
    });
  }

  Future<void> _sendCode({required bool initial}) async {
    final email = widget.email?.trim() ?? '';
    if (email.isEmpty) {
      setState(() => _error = '缺少邮箱地址，请返回重新输入');
      return;
    }
    if (_sending) return;
    setState(() => _sending = true);
    try {
      await _repo.requestEmailCode(email);
      if (!mounted) return;
      _notice(initial ? '验证码已发送，请查收邮箱' : '验证码已重新发送');
      _startCountdown();
    } on AuthCodeException catch (e) {
      if (!mounted) return;
      _notice(e.message);
      final retry = e.retryAfterSeconds ?? 0;
      if (retry > 0) _startCountdown(seconds: retry);
    } catch (_) {
      if (!mounted) return;
      _notice('验证码发送失败，请稍后重试');
    } finally {
      if (mounted) setState(() => _sending = false);
    }
  }

  void _onResend() {
    FocusScope.of(context).unfocus();
    if (_countdown > 0 || _sending) return;
    _sendCode(initial: false);
  }

  void _onHelp() {
    FocusScope.of(context).unfocus();
    _notice('收不到验证码？看看垃圾箱，或稍后点「重新发送」');
  }

  /// 返回登录页：先收起键盘，避免返回后键盘仍压在登录页上。
  void _editEmail() {
    FocusScope.of(context).unfocus();
    if (context.canPop()) {
      context.pop();
    } else {
      context.go('/login');
    }
  }

  Future<void> _startFirstDay() async {
    FocusScope.of(context).unfocus();
    if (!_codePattern.hasMatch(_code.text.trim())) {
      setState(() => _error = '请输入 6 位验证码');
      return;
    }
    if (!_agreed) {
      setState(() => _error = '请先阅读并同意《用户协议》和《隐私政策》');
      return;
    }
    final email = widget.email?.trim() ?? '';
    if (email.isEmpty) {
      setState(() => _error = '缺少邮箱地址，请返回重新输入');
      return;
    }
    if (_verifying) return;
    setState(() {
      _verifying = true;
      _error = null;
    });
    try {
      final deviceId = DateTime.now().millisecondsSinceEpoch.toRadixString(36);
      await _repo.verifyEmailCode(
        email: email,
        code: _code.text.trim(),
        deviceId: deviceId,
        platform: Theme.of(context).platform.name,
      );
      final prefs = await PrefsStore.load();
      final nickname = _nickname.text.trim();
      if (nickname.isNotEmpty) {
        await prefs.setNickname(nickname);
      }
      await prefs.setLastEmail(email);
      await prefs.markLoginSeen();
      if (!mounted) return;
      context.go('/home');
    } on AuthCodeException catch (e) {
      if (!mounted) return;
      setState(() {
        _verifying = false;
        _error = e.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _verifying = false;
        _error = '登录失败，请检查网络后重试';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 8, 18, 32),
          children: [
            BackLink(label: '‹ 返回', onTap: _editEmail),
            const SizedBox(height: 4),
            Row(
              children: [
                const Orb(size: OrbSize.md),
                const SizedBox(width: 10),
                Text(
                  '亚丝娜 · 初次见面',
                  style: type.sub.copyWith(color: colors.ink2),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              '输入邮箱验证码',
              style: type.pageTitle.copyWith(fontSize: 26, color: colors.ink),
            ),
            const SizedBox(height: 8),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '6 位验证码已发送至 ',
                  style: type.body.copyWith(
                    fontSize: 13.5,
                    color: colors.ink2,
                  ),
                ),
                Flexible(
                  child: Text(
                    _maskedEmail,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: type.body.copyWith(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w600,
                      color: colors.ink,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                GestureDetector(
                  onTap: _editEmail,
                  behavior: HitTestBehavior.opaque,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Text(
                      '修改',
                      style: type.body.copyWith(
                        fontSize: 12.5,
                        fontWeight: FontWeight.w600,
                        color: colors.aiBlue,
                      ),
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 22),
            _CodeRow(
              controller: _code,
              focusNode: _codeFocus,
              hasError: _error != null,
            ),
            const SizedBox(height: 18),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                _countdown > 0
                    ? Row(
                        crossAxisAlignment: CrossAxisAlignment.baseline,
                        textBaseline: TextBaseline.alphabetic,
                        children: [
                          Text(
                            '$_countdown s',
                            style: type.rowTitle.copyWith(
                              fontSize: 12.5,
                              fontWeight: FontWeight.w700,
                              color: colors.aiPrimary,
                            ),
                          ),
                          const SizedBox(width: 4),
                          Text(
                            '后可重新发送',
                            style: type.sub.copyWith(
                              fontSize: 12.5,
                              color: colors.ink3,
                            ),
                          ),
                        ],
                      )
                    : GestureDetector(
                        onTap: _onResend,
                        behavior: HitTestBehavior.opaque,
                        child: Text(
                          '重新发送',
                          style: type.rowTitle.copyWith(
                            fontSize: 12.5,
                            fontWeight: FontWeight.w700,
                            color: colors.aiPrimary,
                          ),
                        ),
                      ),
                GestureDetector(
                  onTap: _onHelp,
                  behavior: HitTestBehavior.opaque,
                  child: Text(
                    '收不到验证码？',
                    style: type.rowTitle.copyWith(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                      color: colors.aiBlue,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 26),
            _FieldCard(
              prefix: Icon(AppIcons.sparkles,
                  size: 16, color: colors.aiPrimary),
              hint: '想让我怎么称呼你？（选填）',
              controller: _nickname,
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: type.rowTitle.copyWith(
                  fontSize: 12.5,
                  color: colors.danger,
                ),
              ),
            ],
            const SizedBox(height: 24),
            GestureDetector(
              onTap: _verifying ? null : _startFirstDay,
              behavior: HitTestBehavior.opaque,
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 15),
                decoration: BoxDecoration(
                  gradient: context.gradients.ai,
                  borderRadius: context.radii.rFull,
                  boxShadow: context.elevation.btnPrimary,
                ),
                child: Center(
                  child: Text(
                    _verifying ? '验证中…' : '开始我们的第一天',
                    style: type.rowTitle.copyWith(
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                      color: colors.onDeepPrimary,
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 14),
            AgreementCheck(
              checked: _agreed,
              onToggle: () => setState(() => _agreed = !_agreed),
            ),
            const SizedBox(height: 26),
            Container(
              padding: const EdgeInsets.fromLTRB(16, 15, 16, 15),
              decoration: BoxDecoration(
                color: colors.health.withValues(alpha: 0.07),
                borderRadius: context.radii.rMd,
                border: Border.all(
                  color: colors.health.withValues(alpha: 0.18),
                ),
              ),
              child: Text(
                '你的数据只属于你：可随时查看、导出或一键清空；未经你授权，健康数据不会上传。',
                style: type.sub.copyWith(
                  fontSize: 12,
                  height: 1.7,
                  color: colors.privacyText,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 6 格分段验证码：隐形 TextField 承载输入与键盘，格子只做视觉。
class _CodeRow extends StatelessWidget {
  const _CodeRow({
    required this.controller,
    required this.focusNode,
    required this.hasError,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final bool hasError;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => focusNode.requestFocus(),
      behavior: HitTestBehavior.opaque,
      child: Stack(
        alignment: Alignment.center,
        children: [
          AnimatedBuilder(
            animation: Listenable.merge([controller, focusNode]),
            builder: (context, _) {
              final children = <Widget>[];
              for (var i = 0; i < 6; i++) {
                if (i > 0) children.add(const SizedBox(width: 8));
                children.add(
                  Expanded(
                    child: _CodeCell(
                      character: i < controller.text.length
                          ? controller.text[i]
                          : null,
                      filled: i < controller.text.length,
                      focused:
                          focusNode.hasFocus && i == controller.text.length,
                      hasError: hasError,
                    ),
                  ),
                );
              }
              return Row(children: children);
            },
          ),
          SizedBox(
            height: 58,
            width: double.infinity,
            child: Opacity(
              opacity: 0,
              child: TextField(
                key: const Key('verify_code_field'),
                controller: controller,
                focusNode: focusNode,
                autofocus: true,
                maxLength: 6,
                keyboardType: TextInputType.number,
                inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                decoration: const InputDecoration(
                  border: InputBorder.none,
                  counterText: '',
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CodeCell extends StatelessWidget {
  const _CodeCell({
    required this.character,
    required this.filled,
    required this.focused,
    required this.hasError,
  });

  final String? character;
  final bool filled;
  final bool focused;
  final bool hasError;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final radii = BorderRadius.circular(14);
    final cell = Container(
      alignment: Alignment.center,
      height: 58,
      decoration: BoxDecoration(
        color:
            hasError ? colors.danger.withValues(alpha: 0.05) : colors.surface,
        borderRadius: radii,
        border: hasError
            ? Border.all(color: colors.danger.withValues(alpha: 0.55), width: 1.5)
            : null,
        boxShadow:
            hasError || focused ? null : context.elevation.card,
      ),
      child: character != null
          ? Text(
              character!,
              style: type.pageTitle.copyWith(
                fontSize: 22,
                fontWeight: FontWeight.w700,
                color: hasError ? colors.danger : colors.ink,
              ),
            )
          : (focused ? const _BlinkingCaret() : null),
    );
    if (focused && !hasError) {
      return AnimatedScale(
        scale: filled ? 1.04 : 1,
        duration: const Duration(milliseconds: 150),
        child: Container(
          padding: const EdgeInsets.all(1.5),
          decoration: BoxDecoration(
            gradient: context.gradients.ai,
            borderRadius: radii,
            boxShadow: context.elevation.btnPrimary,
          ),
          child: Container(
            alignment: Alignment.center,
            height: 55,
            decoration: BoxDecoration(
              color: colors.surface,
              borderRadius: radii,
            ),
            child: character != null
                ? Text(
                    character!,
                    style: type.pageTitle.copyWith(
                      fontSize: 22,
                      fontWeight: FontWeight.w700,
                      color: colors.ink,
                    ),
                  )
                : const _BlinkingCaret(),
          ),
        ),
      );
    }
    return AnimatedScale(
      scale: filled ? 1.04 : 1,
      duration: const Duration(milliseconds: 150),
      child: cell,
    );
  }
}

class _BlinkingCaret extends StatefulWidget {
  const _BlinkingCaret();

  @override
  State<_BlinkingCaret> createState() => _BlinkingCaretState();
}

class _BlinkingCaretState extends State<_BlinkingCaret>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  )..repeat();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        // steps(1)：无渐变，前半显示后半隐藏
        return Opacity(
          opacity: _controller.value < 0.5 ? 1 : 0,
          child: Container(
            width: 2.5,
            height: 24,
            decoration: BoxDecoration(
              color: colors.aiPrimary,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
        );
      },
    );
  }
}

class _FieldCard extends StatelessWidget {
  const _FieldCard({
    required this.hint,
    required this.controller,
    this.prefix,
  });

  final String hint;
  final TextEditingController controller;
  final Widget? prefix;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    return Container(
      height: 54,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rMd,
        boxShadow: context.elevation.card,
      ),
      child: Row(
        children: [
          if (prefix != null) ...[
            prefix!,
            const SizedBox(width: 10),
          ],
          Expanded(
            child: TextField(
              controller: controller,
              style: type.body.copyWith(fontSize: 15, color: colors.ink),
              decoration: InputDecoration(
                hintText: hint,
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
