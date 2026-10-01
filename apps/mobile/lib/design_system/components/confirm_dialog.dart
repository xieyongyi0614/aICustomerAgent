import 'package:flutter/material.dart';

import '../tokens/tokens.dart';
import 'press_scale.dart';

/// 确认弹窗（白卡 rLg）：图标方块 36 / 圆角 12 + 居中标题与说明 + 并排两枚 pill 按钮。
///
/// 底色/字色全部走 token：危险动作 = `dangerBg` 底 + `dangerText` 字（A36 口径），
/// 次级动作用 `fillSubtle` 底，均不使用 ai 渐变（用户动作不属于 AI 语义）。
Future<bool> showConfirmDialog({
  required BuildContext context,
  required String title,
  required String message,
  required String confirmLabel,
  String cancelLabel = '取消',
  IconData icon = AppIcons.alert,
  bool danger = false,
}) async {
  final colors = Theme.of(context).extension<AppColors>()!;
  final confirmed = await showDialog<bool>(
    context: context,
    barrierColor: colors.ink.withValues(alpha: 0.38),
    builder: (dialogContext) => ConfirmDialog(
      title: title,
      message: message,
      confirmLabel: confirmLabel,
      cancelLabel: cancelLabel,
      icon: icon,
      danger: danger,
    ),
  );
  return confirmed ?? false;
}

class ConfirmDialog extends StatelessWidget {
  const ConfirmDialog({
    super.key,
    required this.title,
    required this.message,
    required this.confirmLabel,
    this.cancelLabel = '取消',
    this.icon = AppIcons.alert,
    this.danger = false,
  });

  final String title;
  final String message;
  final String confirmLabel;
  final String cancelLabel;
  final IconData icon;
  final bool danger;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    return Dialog(
      backgroundColor: colors.transparent,
      surfaceTintColor: colors.transparent,
      elevation: 0,
      insetPadding: const EdgeInsets.symmetric(horizontal: 44, vertical: 24),
      child: Container(
        padding: const EdgeInsets.fromLTRB(20, 22, 20, 16),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radii.rLg,
          boxShadow: elevation.card,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(
                color: danger ? colors.dangerBg : colors.fillSubtle,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(
                icon,
                size: 18,
                color: danger ? colors.dangerText : colors.ink2,
              ),
            ),
            const SizedBox(height: 14),
            Text(
              title,
              textAlign: TextAlign.center,
              style: type.pageTitle.copyWith(
                fontSize: 17,
                fontWeight: FontWeight.w700,
                color: colors.ink,
              ),
            ),
            const SizedBox(height: 8),
            Text(
              message,
              textAlign: TextAlign.center,
              style: type.body.copyWith(
                fontSize: 13.5,
                height: 1.7,
                color: colors.ink2,
              ),
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: _DialogButton(
                    key: const Key('confirm_dialog_cancel'),
                    label: cancelLabel,
                    background: colors.fillSubtle,
                    foreground: colors.ink2,
                    onTap: () => Navigator.of(context).pop(false),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: _DialogButton(
                    key: const Key('confirm_dialog_confirm'),
                    label: confirmLabel,
                    background: danger ? colors.dangerBg : colors.ink,
                    foreground:
                        danger ? colors.dangerText : colors.onDeepPrimary,
                    onTap: () => Navigator.of(context).pop(true),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _DialogButton extends StatelessWidget {
  const _DialogButton({
    super.key,
    required this.label,
    required this.background,
    required this.foreground,
    required this.onTap,
  });

  final String label;
  final Color background;
  final Color foreground;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    return PressScale(
      onTap: onTap,
      child: Container(
        alignment: Alignment.center,
        padding: const EdgeInsets.symmetric(vertical: 12),
        decoration: BoxDecoration(
          color: background,
          borderRadius: radii.rFull,
        ),
        child: Text(
          label,
          style: type.rowTitle.copyWith(
            fontSize: 13.5,
            fontWeight: FontWeight.w600,
            color: foreground,
          ),
        ),
      ),
    );
  }
}
