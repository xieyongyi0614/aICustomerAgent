import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

AppColors _c(BuildContext context) =>
    Theme.of(context).extension<AppColors>()!;
AppTypography _t(BuildContext context) =>
    Theme.of(context).extension<AppTypography>()!;
AppRadii _r(BuildContext context) => Theme.of(context).extension<AppRadii>()!;
AppElevation _e(BuildContext context) =>
    Theme.of(context).extension<AppElevation>()!;

/// A41 picker-sheet：底部选择面板（把手 + 标题 + 取消 / 完成）。
///
/// 面板离屏 12 浮起、四角 rLg、白底 + 柔和投影；「完成」把 [result] 的求值结果
/// 作为 Future 返回，「取消」与点遮罩返回 null。用户动作取 `ink` 深色，不用 ai 色。
Future<T?> showPickerSheet<T>({
  required BuildContext context,
  required String title,
  required Widget child,
  T? Function()? result,
  String confirmLabel = '完成',
  String cancelLabel = '取消',
  bool confirmEnabled = true,
}) {
  final colors = Theme.of(context).extension<AppColors>()!;
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    backgroundColor: colors.transparent,
    barrierColor: colors.ink.withValues(alpha: 0.34),
    builder: (sheetContext) => _PickerSheetFrame(
      title: title,
      confirmLabel: confirmLabel,
      cancelLabel: cancelLabel,
      confirmEnabled: confirmEnabled,
      onConfirm: () => Navigator.of(sheetContext).pop(result?.call()),
      onCancel: () => Navigator.of(sheetContext).pop(),
      child: child,
    ),
  );
}

class _PickerSheetFrame extends StatelessWidget {
  const _PickerSheetFrame({
    required this.title,
    required this.child,
    required this.onConfirm,
    required this.onCancel,
    required this.confirmLabel,
    required this.cancelLabel,
    required this.confirmEnabled,
  });

  final String title;
  final Widget child;
  final VoidCallback onConfirm;
  final VoidCallback onCancel;
  final String confirmLabel;
  final String cancelLabel;
  final bool confirmEnabled;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    final elevation = _e(context);
    final media = MediaQuery.of(context);
    return SafeArea(
      top: false,
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          12,
          8,
          12,
          media.viewPadding.bottom > 0 ? 8 : 14,
        ),
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: media.size.height * 0.72),
          child: Container(
            decoration: BoxDecoration(
              color: colors.surface,
              borderRadius: radii.rLg,
              boxShadow: elevation.deep,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const SizedBox(height: 10),
                Container(
                  width: 38,
                  height: 4,
                  decoration: BoxDecoration(
                    color: colors.line,
                    borderRadius: radii.rFull,
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(18, 12, 12, 6),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          title,
                          style: type.title.copyWith(
                            fontSize: 16.5,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      _SheetAction(
                        label: cancelLabel,
                        color: colors.ink2,
                        onTap: onCancel,
                      ),
                      const SizedBox(width: 14),
                      _SheetAction(
                        label: confirmLabel,
                        color: colors.ink,
                        bold: true,
                        onTap: confirmEnabled ? onConfirm : null,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 2),
                Flexible(child: child),
                const SizedBox(height: 8),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SheetAction extends StatelessWidget {
  const _SheetAction({
    required this.label,
    required this.color,
    this.onTap,
    this.bold = false,
  });

  final String label;
  final Color color;
  final VoidCallback? onTap;
  final bool bold;

  @override
  Widget build(BuildContext context) {
    final type = _t(context);
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Opacity(
        opacity: onTap == null ? 0.4 : 1,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 2),
          child: Text(
            label,
            style: type.label.copyWith(
              fontSize: 14,
              letterSpacing: 0,
              fontWeight: bold ? FontWeight.w700 : FontWeight.w600,
              color: color,
            ),
          ),
        ),
      ),
    );
  }
}

/// A41 wheel：单列滚轮（40 高一档、选中档 fillSubtle 底），滚动即回调。
class WheelColumn extends StatefulWidget {
  const WheelColumn({
    super.key,
    required this.items,
    required this.initialIndex,
    this.onChanged,
    this.width,
  });

  final List<String> items;
  final int initialIndex;
  final ValueChanged<int>? onChanged;
  final double? width;

  @override
  State<WheelColumn> createState() => _WheelColumnState();
}

class _WheelColumnState extends State<WheelColumn> {
  static const _itemExtent = 40.0;
  late int _index = widget.initialIndex.clamp(0, widget.items.length - 1);
  late final FixedExtentScrollController _controller =
      FixedExtentScrollController(initialItem: _index);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    return SizedBox(
      width: widget.width,
      height: _itemExtent * 5,
      child: ListWheelScrollView.useDelegate(
        controller: _controller,
        itemExtent: _itemExtent,
        perspective: 0.002,
        diameterRatio: 1.7,
        physics: const FixedExtentScrollPhysics(),
        onSelectedItemChanged: (index) {
          setState(() => _index = index);
          widget.onChanged?.call(index);
        },
        childDelegate: ListWheelChildBuilderDelegate(
          childCount: widget.items.length,
          builder: (context, index) => Container(
            alignment: Alignment.center,
            decoration: index == _index
                ? BoxDecoration(
                    color: colors.fillSubtle,
                    borderRadius: radii.rSm,
                  )
                : null,
            child: Text(
              widget.items[index],
              style: type.numeric(type.body).copyWith(
                fontSize: 16,
                fontWeight: index == _index ? FontWeight.w700 : FontWeight.w400,
                color: index == _index ? colors.ink : colors.ink3,
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// A41 date-wheel：年 / 月 / 日三列滚轮，返回所选日期（不含时间）。
Future<DateTime?> showDateWheelSheet({
  required BuildContext context,
  required String title,
  DateTime? initial,
  DateTime? firstDate,
  DateTime? lastDate,
}) {
  final today = DateUtils.dateOnly(DateTime.now());
  final minDate = firstDate ?? DateTime(today.year - 1, 1, 1);
  final maxDate = lastDate ?? DateTime(today.year + 20, 12, 31);
  final raw = initial ?? today;
  final start = DateUtils.dateOnly(
    raw.isBefore(minDate) ? minDate : (raw.isAfter(maxDate) ? maxDate : raw),
  );
  var selected = start;
  return showPickerSheet<DateTime>(
    context: context,
    title: title,
    result: () => selected,
    child: _DateWheelContent(
      initial: start,
      firstDate: minDate,
      lastDate: maxDate,
      onChanged: (value) => selected = value,
    ),
  );
}

class _DateWheelContent extends StatefulWidget {
  const _DateWheelContent({
    required this.initial,
    required this.firstDate,
    required this.lastDate,
    required this.onChanged,
  });

  final DateTime initial;
  final DateTime firstDate;
  final DateTime lastDate;
  final ValueChanged<DateTime> onChanged;

  @override
  State<_DateWheelContent> createState() => _DateWheelContentState();
}

class _DateWheelContentState extends State<_DateWheelContent> {
  late int _year = widget.initial.year;
  late int _month = widget.initial.month;
  late int _day = widget.initial.day;

  int get _minYear => widget.firstDate.year;
  int get _maxYear => widget.lastDate.year;
  int get _dayCount => DateUtils.getDaysInMonth(_year, _month);

  void _emit() => widget.onChanged(DateTime(_year, _month, _day));

  @override
  Widget build(BuildContext context) {
    final years = [for (var y = _minYear; y <= _maxYear; y++) '$y'];
    final months = [for (var m = 1; m <= 12; m++) '$m 月'];
    final days = [for (var d = 1; d <= _dayCount; d++) '$d 日'];
    _day = _day.clamp(1, _dayCount);
    return Padding(
      padding: const EdgeInsets.fromLTRB(18, 4, 18, 6),
      child: Row(
        children: [
          Expanded(
            child: WheelColumn(
              items: years,
              initialIndex: _year - _minYear,
              onChanged: (index) {
                _year = _minYear + index;
                _day = _day.clamp(1, _dayCount);
                _emit();
                setState(() {});
              },
            ),
          ),
          Expanded(
            child: WheelColumn(
              items: months,
              initialIndex: _month - 1,
              onChanged: (index) {
                _month = index + 1;
                _day = _day.clamp(1, _dayCount);
                _emit();
                setState(() {});
              },
            ),
          ),
          Expanded(
            child: WheelColumn(
              items: days,
              initialIndex: _day - 1,
              onChanged: (index) {
                _day = index + 1;
                _emit();
              },
            ),
          ),
        ],
      ),
    );
  }
}

/// picker 搜索框的 key（用例与自动化定位用）。
const pickerSearchKey = ValueKey<String>('picker-search');

/// A41 choice-sheet 条目：`group` 用于分组头，`note` 是行尾说明（如动力类型）。
class ChoiceSheetItem<T> {
  const ChoiceSheetItem({
    required this.value,
    required this.label,
    this.group,
    this.note,
  });

  final T value;
  final String label;
  final String? group;
  final String? note;
}

/// A41 choice-sheet：单选列表（可按品牌等分组、可搜索）。
///
/// [freeTextBuilder] 给出时，搜索词会作为首行「用「xxx」」进入选择——
/// 目录外的车型（用户自己的写法）不用另建入口，直接落到这一行。
Future<T?> showChoiceSheet<T>({
  required BuildContext context,
  required String title,
  required List<ChoiceSheetItem<T>> items,
  T? selected,
  bool searchable = false,
  String searchHint = '搜索',
  T? Function(String query)? freeTextBuilder,
}) {
  return showPickerSheet<T>(
    context: context,
    title: title,
    child: _ChoiceSheetContent<T>(
      items: items,
      selected: selected,
      searchable: searchable,
      searchHint: searchHint,
      freeTextBuilder: freeTextBuilder,
    ),
  );
}

class _ChoiceSheetContent<T> extends StatefulWidget {
  const _ChoiceSheetContent({
    required this.items,
    required this.selected,
    required this.searchable,
    required this.searchHint,
    required this.freeTextBuilder,
  });

  final List<ChoiceSheetItem<T>> items;
  final T? selected;
  final bool searchable;
  final String searchHint;
  final T? Function(String query)? freeTextBuilder;

  @override
  State<_ChoiceSheetContent<T>> createState() => _ChoiceSheetContentState<T>();
}

class _ChoiceSheetContentState<T> extends State<_ChoiceSheetContent<T>> {
  final _query = TextEditingController();

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  List<ChoiceSheetItem<T>> get _visible {
    final keyword = _query.text.trim().toLowerCase();
    if (keyword.isEmpty) return widget.items;
    return [
      for (final item in widget.items)
        if (item.label.toLowerCase().contains(keyword) ||
            (item.group ?? '').toLowerCase().contains(keyword))
          item,
    ];
  }

  T? get _freeText {
    final build = widget.freeTextBuilder;
    if (build == null) return null;
    final keyword = _query.text.trim();
    if (keyword.isEmpty) return null;
    final matched = _visible.any((item) => item.label == keyword);
    return matched ? null : build(keyword);
  }

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    final visible = _visible;
    final freeText = _freeText;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (widget.searchable)
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 2, 18, 10),
            child: Container(
              padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 14),
              decoration: BoxDecoration(
                color: colors.fillSubtle,
                borderRadius: radii.rFull,
              ),
              child: TextField(
                key: pickerSearchKey,
                controller: _query,
                onChanged: (_) => setState(() {}),
                style: type.body.copyWith(fontSize: 14),
                decoration: InputDecoration.collapsed(
                  hintText: widget.searchHint,
                  hintStyle: type.body
                      .copyWith(fontSize: 14, color: colors.ink3),
                ),
              ),
            ),
          ),
        Flexible(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(18, 2, 18, 4),
            shrinkWrap: true,
            children: [
              if (freeText != null)
                _row(
                  context,
                  label: '用「${_query.text.trim()}」',
                  note: '目录里没有就照你写的记',
                  onTap: () => Navigator.of(context).pop(freeText),
                ),
              for (var index = 0; index < visible.length; index++) ...[
                if (_showGroup(index, visible))
                  Padding(
                    padding: EdgeInsets.only(
                      top: index == 0 ? 2 : 14,
                      bottom: 4,
                    ),
                    child: Text(
                      visible[index].group!,
                      style: type.caption.copyWith(
                        fontSize: 12,
                        color: colors.ink3,
                      ),
                    ),
                  ),
                _row(
                  context,
                  label: visible[index].label,
                  note: visible[index].note,
                  checked: visible[index].value == widget.selected,
                  onTap: () =>
                      Navigator.of(context).pop(visible[index].value),
                ),
              ],
              if (visible.isEmpty && freeText == null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 18),
                  child: Text(
                    '没找到，换个关键词试试',
                    textAlign: TextAlign.center,
                    style: type.caption.copyWith(color: colors.ink3),
                  ),
                ),
            ],
          ),
        ),
      ],
    );
  }

  bool _showGroup(int index, List<ChoiceSheetItem<T>> visible) {
    final group = visible[index].group;
    if (group == null) return false;
    if (index == 0) return true;
    return visible[index - 1].group != group;
  }

  Widget _row(
    BuildContext context, {
    required String label,
    required VoidCallback onTap,
    String? note,
    bool checked = false,
  }) {
    final colors = _c(context);
    final type = _t(context);
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 13),
        decoration: BoxDecoration(
          border: Border(bottom: BorderSide(color: colors.line)),
        ),
        child: Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: type.body.copyWith(
                  fontWeight: checked ? FontWeight.w600 : FontWeight.w500,
                  color: colors.ink,
                ),
              ),
            ),
            if (note != null)
              Padding(
                padding: const EdgeInsets.only(left: 10),
                child: Text(
                  note,
                  style: type.caption.copyWith(color: colors.ink3),
                ),
              ),
            if (checked)
              Padding(
                padding: const EdgeInsets.only(left: 10),
                child: Icon(AppIcons.check, size: 16, color: colors.ink),
              ),
          ],
        ),
      ),
    );
  }
}
