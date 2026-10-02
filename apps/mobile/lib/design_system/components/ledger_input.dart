import 'package:flutter/material.dart';

import '../tokens/tokens.dart';
import 'gradient_border_card.dart';
import 'press_scale.dart';
import 'sparkle.dart';

/// A32 seg 选项
class LedgerSegOption {
  const LedgerSegOption({required this.value, required this.label});

  final String value;
  final String label;
}

/// A32 seg（支出 / 收入分段）
class LedgerSeg extends StatelessWidget {
  const LedgerSeg({
    super.key,
    required this.options,
    required this.value,
    this.onChanged,
  });

  final List<LedgerSegOption> options;
  final String value;
  final ValueChanged<String>? onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: colors.fillMuted,
        borderRadius: radii.rFull,
      ),
      child: Row(
        children: [
          for (final option in options)
            Expanded(
              child: GestureDetector(
                onTap: onChanged == null ? null : () => onChanged!(option.value),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  decoration: BoxDecoration(
                    color: option.value == value ? colors.surface : colors.transparent,
                    borderRadius: radii.rFull,
                    boxShadow: option.value == value
                        ? [
                            BoxShadow(
                              color: colors.ink.withValues(alpha: 0.08),
                              offset: const Offset(0, 2),
                              blurRadius: 8,
                            ),
                          ]
                        : null,
                  ),
                  child: Text(
                    option.label,
                    textAlign: TextAlign.center,
                    style: type.caption.copyWith(
                      fontSize: 13.5,
                      fontWeight: FontWeight.w600,
                      color: option.value == value ? colors.ink : colors.ink2,
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// A32 amount（金额区）
class LedgerAmount extends StatelessWidget {
  const LedgerAmount({
    super.key,
    required this.label,
    required this.amountText,
    this.currency = '¥',
    this.focused = true,
  });

  final String label;
  final String amountText;
  final String currency;
  final bool focused;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final spacing = Theme.of(context).extension<AppSpacing>()!;
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: spacing.cardPadding,
        vertical: spacing.cardPaddingSm,
      ),
      decoration: BoxDecoration(color: colors.surface, borderRadius: radii.rLg),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Text(
            label,
            style: type.caption.copyWith(
              fontSize: 12,
              color: colors.ink3,
              fontWeight: FontWeight.w400,
            ),
          ),
          const Spacer(),
          Text(
            currency,
            style: type.amountHero.copyWith(fontSize: 22, letterSpacing: -0.44),
          ),
          const SizedBox(width: 4),
          Text(
            amountText,
            style: type.amountHero.copyWith(fontSize: 38, letterSpacing: -0.76),
          ),
          if (focused) const _BlinkCursor(),
        ],
      ),
    );
  }
}

class _BlinkCursor extends StatefulWidget {
  const _BlinkCursor();

  @override
  State<_BlinkCursor> createState() => _BlinkCursorState();
}

class _BlinkCursorState extends State<_BlinkCursor>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1100),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    return Padding(
      padding: const EdgeInsets.only(left: 3),
      child: AnimatedBuilder(
        animation: _controller,
        builder: (context, child) => Opacity(
          opacity: _controller.value < 0.5 ? 1 : 0,
          child: child,
        ),
        child: Container(
          width: 2,
          height: 30,
          decoration: BoxDecoration(
            color: colors.money,
            borderRadius: BorderRadius.circular(1),
          ),
        ),
      ),
    );
  }
}

/// A32 kind 宫格项
class LedgerKindItem {
  const LedgerKindItem({
    required this.key,
    required this.label,
    required this.icon,
  });

  final String key;
  final String label;
  final IconData icon;
}

/// A32 kind（分类宫格）：4 列，选中边框取记账域 money 色。
class LedgerKindGrid extends StatelessWidget {
  const LedgerKindGrid({
    super.key,
    required this.items,
    this.selectedKey,
    this.onSelected,
  });

  final List<LedgerKindItem> items;
  final String? selectedKey;
  final ValueChanged<String>? onSelected;

  @override
  Widget build(BuildContext context) {
    final radii = Theme.of(context).extension<AppRadii>()!;
    final rows = <Widget>[];
    for (var start = 0; start < items.length; start += 4) {
      final rowItems = items.skip(start).take(4).toList();
      rows.add(
        Row(
          children: [
            for (var index = 0; index < 4; index++) ...[
              if (index > 0) const SizedBox(width: 9),
              Expanded(
                child: index < rowItems.length
                    ? _cell(context, rowItems[index], radii)
                    : const SizedBox.shrink(),
              ),
            ],
          ],
        ),
      );
    }
    final colors = Theme.of(context).extension<AppColors>()!;
    return Container(
      padding: const EdgeInsets.fromLTRB(4, 11, 4, 9),
      decoration: BoxDecoration(color: colors.surface, borderRadius: radii.rMd),
      child: Column(
        children: [
          for (var index = 0; index < rows.length; index++) ...[
            if (index > 0) const SizedBox(height: 9),
            rows[index],
          ],
        ],
      ),
    );
  }

  Widget _cell(BuildContext context, LedgerKindItem item, AppRadii radii) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final selected = item.key == selectedKey;
    return GestureDetector(
      onTap: onSelected == null ? null : () => onSelected!(item.key),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 6),
        decoration: BoxDecoration(
          borderRadius: radii.rSm,
          border: Border.all(
            width: 1.5,
            color: selected
                ? colors.money.withValues(alpha: 0.55)
                : colors.transparent,
          ),
        ),
        child: Column(
          children: [
            Container(
              width: 34,
              height: 34,
              decoration: BoxDecoration(
                color: colors.tileMoney,
                borderRadius: BorderRadius.circular(radii.iconTile(34)),
              ),
              child: Icon(item.icon, size: 17, color: colors.money),
            ),
            const SizedBox(height: 6),
            Text(
              item.label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: type.caption.copyWith(
                fontSize: 11.5,
                fontWeight: FontWeight.w600,
                color: selected ? colors.ink : colors.ink2,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// A32 form 行
class LedgerFormRow {
  const LedgerFormRow({
    required this.label,
    this.value,
    this.placeholder,
    this.helper,
    this.onTap,
  });

  final String label;
  final String? value;
  final String? placeholder;
  final String? helper;
  final VoidCallback? onTap;
}

/// A32 form（表单行）：白卡，行间以 `line` 分割。
class LedgerFormRows extends StatelessWidget {
  const LedgerFormRows({
    super.key,
    required this.rows,
    this.labelWidth = 60,
  });

  final List<LedgerFormRow> rows;
  final double labelWidth;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 18),
      decoration: BoxDecoration(color: colors.surface, borderRadius: radii.rLg),
      child: Column(
        children: [
          for (var index = 0; index < rows.length; index++)
            _row(context, colors, rows[index], index < rows.length - 1),
        ],
      ),
    );
  }

  Widget _row(
    BuildContext context,
    AppColors colors,
    LedgerFormRow row,
    bool showDivider,
  ) {
    final type = Theme.of(context).extension<AppTypography>()!;
    final filled = row.value != null && row.value!.isNotEmpty;
    return GestureDetector(
      onTap: row.onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 13),
        decoration: BoxDecoration(
          border:
              showDivider ? Border(bottom: BorderSide(color: colors.line)) : null,
        ),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: labelWidth,
              child: Text(
                row.label,
                style: type.sub.copyWith(
                  fontSize: 13,
                  color: colors.ink2,
                  fontWeight: FontWeight.w400,
                ),
              ),
            ),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    filled ? row.value! : (row.placeholder ?? ''),
                    textAlign: TextAlign.right,
                    style: type.rowTitle.copyWith(
                      color: filled ? colors.ink : colors.ink3,
                      fontWeight: filled ? FontWeight.w600 : FontWeight.w400,
                    ),
                  ),
                  if (row.helper != null) ...[
                    const SizedBox(height: 3),
                    Text(
                      row.helper!,
                      style: type.caption.copyWith(
                        color: colors.ink3,
                        fontWeight: FontWeight.w400,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// A32 pad（数字键盘）
class LedgerPad extends StatelessWidget {
  const LedgerPad({super.key, this.onKey, this.onBackspace});

  final ValueChanged<String>? onKey;
  final VoidCallback? onBackspace;

  static const _digitRows = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
  ];

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    return Container(
      padding: const EdgeInsets.all(9),
      decoration: BoxDecoration(color: colors.surface, borderRadius: radii.rMd),
      child: Column(
        children: [
          for (final row in _digitRows) ...[
            Row(
              children: [
                for (var index = 0; index < row.length; index++) ...[
                  if (index > 0) const SizedBox(width: 9),
                  Expanded(
                    child: _key(context, type, radii, row[index], digit: true),
                  ),
                ],
              ],
            ),
            const SizedBox(height: 9),
          ],
          Row(
            children: [
              Expanded(child: _key(context, type, radii, '.', digit: true)),
              const SizedBox(width: 9),
              Expanded(child: _key(context, type, radii, '0', digit: true)),
              const SizedBox(width: 9),
              Expanded(child: _backspaceKey(context, radii)),
            ],
          ),
        ],
      ),
    );
  }

  Widget _key(
    BuildContext context,
    AppTypography type,
    AppRadii radii,
    String label, {
    bool digit = false,
  }) {
    final colors = Theme.of(context).extension<AppColors>()!;
    return PressScale(
      scale: 0.95,
      onTap: onKey == null ? null : () => onKey!(label),
      child: Container(
        height: 54,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: digit ? colors.fillSubtle : colors.transparent,
          borderRadius: radii.rMd,
        ),
        child: Text(
          label,
          style: type.title.copyWith(
            fontSize: 21,
            fontWeight: FontWeight.w600,
            color: colors.ink,
            fontFeatures: AppTypography.tabular,
          ),
        ),
      ),
    );
  }

  Widget _backspaceKey(BuildContext context, AppRadii radii) {
    final colors = Theme.of(context).extension<AppColors>()!;
    return PressScale(
      scale: 0.95,
      onTap: onBackspace,
      child: Container(
        height: 54,
        alignment: Alignment.center,
        child: Icon(AppIcons.x, size: 20, color: colors.ink2),
      ),
    );
  }
}

/// A33+ say-box（对话录入条）：✦ + 一句话输入 + 示例 chips。
class LedgerSayBox extends StatelessWidget {
  const LedgerSayBox({
    super.key,
    this.controller,
    this.focusNode,
    this.onChanged,
    this.hint = '直接说，例如「午饭一碗拉面 35」',
    this.examples = const ['打车 22', '咖啡 28，不加糖', '昨晚聚餐 186'],
    this.onExampleTap,
  });

  final TextEditingController? controller;
  final FocusNode? focusNode;
  final ValueChanged<String>? onChanged;
  final String hint;
  final List<String> examples;
  final ValueChanged<String>? onExampleTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final elevation = Theme.of(context).extension<AppElevation>()!;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 15, horizontal: 16),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rLg,
        boxShadow: elevation.card,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              SparkleIcon(size: 17, color: colors.aiPrimary),
              const SizedBox(width: 10),
              Expanded(
                child: TextField(
                  controller: controller,
                  focusNode: focusNode,
                  onChanged: onChanged,
                  cursorWidth: 2,
                  cursorColor: colors.aiPrimary,
                  style: type.body.copyWith(color: colors.ink),
                  decoration: InputDecoration.collapsed(
                    hintText: hint,
                    hintStyle: type.body.copyWith(color: colors.ink3),
                  ),
                ),
              ),
            ],
          ),
          if (examples.isNotEmpty) ...[
            const SizedBox(height: 12),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                for (final example in examples)
                  GestureDetector(
                    onTap:
                        onExampleTap == null ? null : () => onExampleTap!(example),
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        vertical: 6,
                        horizontal: 11,
                      ),
                      decoration: BoxDecoration(
                        color: colors.fillSubtle,
                        borderRadius: radii.rFull,
                      ),
                      child: Text(
                        example,
                        style: type.caption.copyWith(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: colors.ink2,
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// A33+ parse 解析行数据。[muted] 表示 AI 没听准的诚实空值态。
class LedgerParseRowData {
  const LedgerParseRowData({
    required this.label,
    required this.value,
    this.note,
    this.muted = false,
  });

  final String label;
  final String value;
  final String? note;
  final bool muted;
}

/// A33+ parse（AI 解析卡「我听到的」）：ai-card 渐变描边变体 + 底部动作行。
///
/// 纪律：解析卡是 AI 语义（渐变描边）；「确认入账」是用户动作，用 `ink` 深色，
/// 禁止 ai 渐变按钮。
class LedgerParseCard extends StatelessWidget {
  const LedgerParseCard({
    super.key,
    required this.rows,
    this.title = '我听到的',
    this.confirmLabel = '确认入账',
    this.onConfirm,
    this.fixLabel = '不对？直接说改哪里',
    this.onFix,
  });

  final List<LedgerParseRowData> rows;
  final String title;
  final String confirmLabel;
  final VoidCallback? onConfirm;
  final String fixLabel;
  final VoidCallback? onFix;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    return GradientBorderCard(
      padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              SparkleIcon(size: 13, color: colors.aiPrimary),
              const SizedBox(width: 7),
              Text(
                title,
                style: type.caption.copyWith(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  letterSpacing: 0.72,
                  color: colors.aiPrimary,
                ),
              ),
            ],
          ),
          const SizedBox(height: 3),
          for (var index = 0; index < rows.length; index++)
            _row(context, rows[index], index < rows.length - 1),
          const SizedBox(height: 13),
          Row(
            children: [
              _confirm(context),
              const SizedBox(width: 8),
              if (onFix != null)
                GestureDetector(
                  onTap: onFix,
                  child: Text(
                    fixLabel,
                    style: type.label.copyWith(
                      fontSize: 12.5,
                      letterSpacing: 0,
                      color: colors.aiPrimary,
                    ),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _row(BuildContext context, LedgerParseRowData row, bool showDivider) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 8),
      decoration: BoxDecoration(
        border: showDivider
            ? Border(bottom: BorderSide(color: colors.line))
            : null,
      ),
      child: Row(
        children: [
          SizedBox(
            width: 56,
            child: Text(
              row.label,
              style: type.caption.copyWith(
                fontSize: 12.5,
                fontWeight: FontWeight.w400,
                color: colors.ink3,
              ),
            ),
          ),
          Expanded(
            child: Text.rich(
              TextSpan(
                children: [
                  TextSpan(text: row.value),
                  if (row.note != null) ...[
                    const TextSpan(text: ' · '),
                    TextSpan(
                      text: row.note,
                      style: TextStyle(
                        fontSize: 11.5,
                        fontWeight: FontWeight.w600,
                        color: colors.ink3,
                      ),
                    ),
                  ],
                ],
              ),
              style: type.numeric(type.rowTitle).copyWith(
                    fontWeight: row.muted ? FontWeight.w400 : FontWeight.w600,
                    color: row.muted ? colors.ink3 : colors.ink,
                  ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _confirm(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    return PressScale(
      onTap: onConfirm,
      child: Opacity(
        opacity: onConfirm == null ? 0.5 : 1,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 18),
          decoration: BoxDecoration(
            color: colors.ink,
            borderRadius: radii.rFull,
            boxShadow: [
              BoxShadow(
                color: colors.ink.withValues(alpha: 0.2),
                offset: const Offset(0, 8),
                blurRadius: 18,
              ),
            ],
          ),
          child: Text(
            confirmLabel,
            style: type.title.copyWith(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: colors.onDeepPrimary,
            ),
          ),
        ),
      ),
    );
  }
}

/// A32 save（深色主按钮）：用户动作，用 `ink` 深色，禁 ai 渐变。
class LedgerSaveButton extends StatelessWidget {
  const LedgerSaveButton({
    super.key,
    required this.label,
    this.onPressed,
    this.enabled = true,
  });

  final String label;
  final VoidCallback? onPressed;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final pressed = enabled ? onPressed : null;
    return PressScale(
      onTap: pressed,
      child: Opacity(
        opacity: enabled ? 1 : 0.5,
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(15),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: colors.ink,
            borderRadius: radii.rFull,
            boxShadow: [
              BoxShadow(
                color: colors.ink.withValues(alpha: 0.22),
                offset: const Offset(0, 12),
                blurRadius: 26,
              ),
            ],
          ),
          child: Text(
            label,
            style: type.title.copyWith(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: colors.onDeepPrimary,
            ),
          ),
        ),
      ),
    );
  }
}
