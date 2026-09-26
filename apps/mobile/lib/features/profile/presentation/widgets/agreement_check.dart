import 'package:flutter/material.dart';

import '../../../../app/theme/theme_context.dart';

/// 登录/验证页底部协议勾选行（原型 .lg-agree）。
class AgreementCheck extends StatelessWidget {
  const AgreementCheck({
    super.key,
    required this.checked,
    required this.onToggle,
  });

  final bool checked;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Center(
      child: GestureDetector(
        onTap: onToggle,
        behavior: HitTestBehavior.opaque,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 12),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 14,
                height: 14,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  border: Border.all(color: colors.borderCheck, width: 1.5),
                ),
                child: checked
                    ? Icon(AppIcons.check, size: 9, color: colors.health)
                    : null,
              ),
              const SizedBox(width: 7),
              Flexible(
                child: Text.rich(
                  TextSpan(
                    text: '已阅读并同意 ',
                    children: [
                      TextSpan(
                        text: '《用户协议》',
                        style: type.label.copyWith(
                          fontSize: 11.5,
                          letterSpacing: 0,
                          color: colors.ink2,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const TextSpan(text: ' 和 '),
                      TextSpan(
                        text: '《隐私政策》',
                        style: type.label.copyWith(
                          fontSize: 11.5,
                          letterSpacing: 0,
                          color: colors.ink2,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                    style: type.label.copyWith(
                      fontSize: 11.5,
                      letterSpacing: 0,
                      color: colors.ink3,
                      fontWeight: FontWeight.w500,
                      height: 1.6,
                    ),
                  ),
                  textAlign: TextAlign.center,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
