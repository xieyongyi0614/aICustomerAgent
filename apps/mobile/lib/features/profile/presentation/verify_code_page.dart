import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';
import 'widgets/agreement_check.dart';

/// 设计稿 ⓪ 手机号验证码：自动注册 + 称呼设置（称呼是亚丝娜的第一条记忆）。
class VerifyCodePage extends StatefulWidget {
  const VerifyCodePage({super.key});

  @override
  State<VerifyCodePage> createState() => _VerifyCodePageState();
}

class _VerifyCodePageState extends State<VerifyCodePage> {
  static const _resendSeconds = 60;
  static final _phonePattern = RegExp(r'^1\d{10}$');

  final _phone = TextEditingController();
  final _code = TextEditingController();
  final _nickname = TextEditingController();
  Timer? _resendTimer;
  int _countdown = 0;
  bool _agreed = true;
  String? _error;

  @override
  void dispose() {
    _phone.dispose();
    _code.dispose();
    _nickname.dispose();
    _resendTimer?.cancel();
    super.dispose();
  }

  bool get _phoneValid => _phonePattern.hasMatch(_phone.text.trim());

  void _sendCode() {
    FocusScope.of(context).unfocus();
    if (!_phoneValid) {
      setState(() => _error = '请输入正确的手机号');
      return;
    }
    setState(() {
      _error = null;
      _countdown = _resendSeconds;
    });
    _resendTimer?.cancel();
    _resendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (_countdown <= 1) {
        timer.cancel();
        if (mounted) setState(() => _countdown = 0);
        return;
      }
      if (mounted) setState(() => _countdown -= 1);
    });
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        behavior: SnackBarBehavior.floating,
        content: Text('验证码通道还没接入，填好信息后直接点「开始我们的第一天」'),
      ),
    );
  }

  Future<void> _startFirstDay() async {
    FocusScope.of(context).unfocus();
    if (!_phoneValid) {
      setState(() => _error = '请输入正确的手机号');
      return;
    }
    if (_code.text.trim().length != 6) {
      setState(() => _error = '请输入 6 位验证码');
      return;
    }
    if (!_agreed) {
      setState(() => _error = '请先阅读并同意《用户协议》和《隐私政策》');
      return;
    }
    final prefs = await PrefsStore.load();
    final nickname = _nickname.text.trim();
    if (nickname.isNotEmpty) {
      await prefs.setNickname(nickname);
    }
    await prefs.markLoginSeen();
    if (!mounted) return;
    context.go('/home');
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
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 8, 18, 32),
          children: [
            BackLink(
              label: '‹ 返回',
              onTap: () =>
                  context.canPop() ? context.pop() : context.go('/login'),
            ),
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
              '手机号登录 / 注册',
              style: type.pageTitle.copyWith(fontSize: 26, color: colors.ink),
            ),
            const SizedBox(height: 6),
            Text(
              '未注册的手机号将自动创建账号',
              style: type.sub.copyWith(color: colors.ink2),
            ),
            const SizedBox(height: 18),
            _FieldCard(
              prefix: Text(
                '+86',
                style: type.rowTitle.copyWith(
                  fontSize: 15,
                  color: colors.ink,
                ),
              ),
              hint: '输入手机号',
              controller: _phone,
              maxLength: 11,
              digitsOnly: true,
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: 12),
            _FieldCard(
              hint: '输入 6 位验证码',
              controller: _code,
              maxLength: 6,
              digitsOnly: true,
              action: GestureDetector(
                onTap: _countdown > 0 ? null : _sendCode,
                behavior: HitTestBehavior.opaque,
                child: Text(
                  _countdown > 0 ? '重发（$_countdown s）' : '获取验证码',
                  style: type.rowTitle.copyWith(
                    fontSize: 13,
                    color:
                        _countdown > 0 ? colors.ink3 : colors.aiPrimary,
                  ),
                ),
              ),
            ),
            const SizedBox(height: 12),
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
                style: type.caption.copyWith(color: colors.warm),
              ),
            ],
            const SizedBox(height: 24),
            GestureDetector(
              onTap: _startFirstDay,
              behavior: HitTestBehavior.opaque,
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 15),
                decoration: BoxDecoration(
                  gradient: context.gradients.ai,
                  borderRadius: radii.rFull,
                  boxShadow: elevation.btnPrimary,
                ),
                child: Center(
                  child: Text(
                    '开始我们的第一天',
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
                borderRadius: radii.rMd,
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

class _FieldCard extends StatelessWidget {
  const _FieldCard({
    required this.hint,
    required this.controller,
    this.prefix,
    this.action,
    this.maxLength,
    this.digitsOnly = false,
    this.onChanged,
  });

  final String hint;
  final TextEditingController controller;
  final Widget? prefix;
  final Widget? action;
  final int? maxLength;
  final bool digitsOnly;
  final ValueChanged<String>? onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rMd,
        boxShadow: context.elevation.pill,
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
              onChanged: onChanged,
              maxLength: maxLength,
              keyboardType:
                  digitsOnly ? TextInputType.number : TextInputType.text,
              inputFormatters: digitsOnly
                  ? [FilteringTextInputFormatter.digitsOnly]
                  : null,
              style: type.body.copyWith(fontSize: 15, color: colors.ink),
              decoration: InputDecoration(
                hintText: hint,
                hintStyle:
                    type.body.copyWith(fontSize: 15, color: colors.ink3),
                border: InputBorder.none,
                counterText: '',
                isCollapsed: true,
                contentPadding: const EdgeInsets.symmetric(vertical: 14),
              ),
            ),
          ),
          if (action != null) ...[
            const SizedBox(width: 10),
            action!,
          ],
        ],
      ),
    );
  }
}
