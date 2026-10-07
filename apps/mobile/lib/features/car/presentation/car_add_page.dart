import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/car_repository.dart';
import '../domain/car_models.dart';

/// B13 #carAdd 养车记一笔：六类型横滑 + 金额 + 随类型切换的表单。
class CarAddPage extends StatefulWidget {
  const CarAddPage({
    super.key,
    this.repository,
    this.linkageHint,
    this.initialKind = 'charge',
  });

  final CarRepository? repository;
  final String? linkageHint;
  final String initialKind;

  @override
  State<CarAddPage> createState() => _CarAddPageState();
}

class _CarAddPageState extends State<CarAddPage> {
  static const _kinds = <String>[
    'charge',
    'fuel',
    'mileage',
    'parking',
    'toll',
    'service',
  ];
  static const _aiHint = '充电可以选择谷电时段，我会按真实记录帮你算账，不猜单价。';

  late final CarRepository _repo = widget.repository ?? CarRepository();
  late final String _idempotencyKey =
      'car-add-${DateTime.now().microsecondsSinceEpoch}';
  late String _kind = widget.initialKind;

  /// 进入页面的时刻：表单里的「时间」行如实显示它，表示这笔记在此刻。
  late final DateTime _recordedAt = DateTime.now();

  final _amount = _AmountBuffer();
  final _kwhController = TextEditingController();
  final _placeController = TextEditingController();
  final _odometerController = TextEditingController();
  final _noteController = TextEditingController();
  final _deltaController = TextEditingController();

  int? _profileOdometer;
  bool _saving = false;
  bool _saveFailed = false;
  String? _validationMessage;

  bool get _isMileage => _kind == 'mileage';

  @override
  void initState() {
    super.initState();
    _loadProfile();
  }

  @override
  void dispose() {
    _kwhController.dispose();
    _placeController.dispose();
    _odometerController.dispose();
    _noteController.dispose();
    _deltaController.dispose();
    super.dispose();
  }

  Future<void> _loadProfile() async {
    try {
      final profile = await _repo.fetchProfile();
      if (!mounted) return;
      setState(() => _profileOdometer = profile.identity?.odometerKm);
    } catch (_) {}
  }

  String get _linkageHint => widget.linkageHint ?? carLinkageHintFallback;

  String get _composedNote {
    final note = _noteController.text.trim();
    if (_kind == 'charge') {
      final kwh = _kwhController.text.trim();
      if (kwh.isEmpty) return note;
      return note.isEmpty ? '$kwh kWh' : '$kwh kWh · $note';
    }
    return note;
  }

  int get _amountMinor {
    if (_isMileage) return 0;
    return _amount.minor;
  }

  int? get _odometerKm {
    if (_isMileage) {
      final delta = int.tryParse(_deltaController.text.trim());
      if (delta == null || delta <= 0) return null;
      final base = _profileOdometer ?? 0;
      return base + delta;
    }
    final text = _odometerController.text.trim();
    if (text.isEmpty) return null;
    return int.tryParse(text);
  }

  String? _validate() {
    if (!_isMileage && _amountMinor <= 0) return '请填入金额';
    if (_kind == 'charge' && _kwhController.text.trim().isEmpty) {
      return '充电需要填度数';
    }
    if (_isMileage && (_odometerKm == null)) return '请填本次里程';
    if (_kind == 'service' && _noteController.text.trim().isEmpty) {
      return '保养需要填项目';
    }
    return null;
  }

  Future<void> _save() async {
    final message = _validate();
    if (message != null) {
      setState(() => _validationMessage = message);
      return;
    }
    setState(() {
      _saving = true;
      _saveFailed = false;
      _validationMessage = null;
    });
    try {
      await _repo.createEntry(
        kind: _kind,
        idempotencyKey: _idempotencyKey,
        amountMinor: _isMileage ? null : _amountMinor,
        note: _composeOutgoingNote(),
        odometerKm: _odometerKm,
        place: _placeController.text.trim().isEmpty
            ? null
            : _placeController.text.trim(),
      );
      if (!mounted) return;
      Navigator.of(context).pop(true);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _saveFailed = true;
      });
    }
  }

  String? _composeOutgoingNote() {
    final note = _composedNote;
    if (_kind == 'mileage') {
      final trimmed = _noteController.text.trim();
      return trimmed.isEmpty ? null : trimmed;
    }
    return note.isEmpty ? null : note;
  }

  void _onKindChanged(String kind) {
    if (kind == _kind) return;
    // 切类型不清空已填内容：用户在几个类型之间来回比价时不该丢输入。
    setState(() {
      _kind = kind;
      _validationMessage = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: ListView(
          padding: context.spacing.screenPadding.copyWith(bottom: 40),
          children: [
            BackLink(label: '车辆'),
            TypeScroll(
              selectedKey: _kind,
              onSelected: _onKindChanged,
              items: [
                for (final kind in _kinds)
                  TypeScrollItem(
                    key: kind,
                    label: _kindLabel(kind),
                    icon: _kindIcon(kind),
                    accent: _kindAccent(context, kind),
                  ),
              ],
            ),
            const SizedBox(height: 14),
            if (!_isMileage) ...[
              LedgerAmount(
                label: '本次金额',
                amountText: _amount.text,
                focused: false,
              ),
              const SizedBox(height: 12),
              LedgerPad(onKey: _onKey, onBackspace: _onBackspace),
              const SizedBox(height: 12),
            ],
            _formCard(context),
            const SizedBox(height: 12),
            AiCard(
              title: '亚丝娜的提示',
              child: Text(
                _aiHint,
                style: type.body.copyWith(color: colors.bodyOnCard, height: 1.6),
              ),
            ),
            const SizedBox(height: 12),
            PrivacyNote(
              child: Text(
                _linkageHint,
                style: type.caption.copyWith(color: colors.ink2, height: 1.6),
              ),
            ),
            const SizedBox(height: 12),
          ],
        ),
      ),
      bottomNavigationBar: _actionBar(context),
    );
  }

  /// 底部常驻动作区：校验 / 失败提示与保存按钮固定在屏底，
  /// 用户填完金额不必滚到底就能保存（页面本身很长：金额键盘 + 表单 + 说明）。
  Widget _actionBar(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Container(
      decoration: BoxDecoration(
        color: colors.canvas,
        border: Border(top: BorderSide(color: colors.line)),
      ),
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 10, 18, 10),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (_validationMessage != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(
                    _validationMessage!,
                    style: type.caption.copyWith(
                      color: colors.danger,
                      fontWeight: FontWeight.w400,
                    ),
                  ),
                ),
              if (_saveFailed)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Row(
                    children: [
                      Expanded(
                        child: Text(
                          StateCopy.networkError,
                          style: type.caption.copyWith(
                            color: colors.danger,
                            fontWeight: FontWeight.w400,
                          ),
                        ),
                      ),
                      ChipButton(
                        label: StateCopy.retryAction,
                        ghost: true,
                        onTap: _save,
                      ),
                    ],
                  ),
                ),
              LedgerSaveButton(
                label: _isMileage ? '保存里程' : '保存记录',
                enabled: !_saving,
                onPressed: _save,
              ),
            ],
          ),
        ),
      ),
    );
  }

  void _onKey(String key) {
    setState(() {
      _validationMessage = null;
      _amount.push(key);
    });
  }

  void _onBackspace() {
    setState(() {
      _validationMessage = null;
      _amount.backspace();
    });
  }

  Widget _formCard(BuildContext context) {
    final colors = context.colors;
    final rows = [..._formRows(context), _readonly(context, '时间', _recordedTimeText)];
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: context.spacing.cardPadding,
        vertical: 4,
      ),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: context.radii.rLg,
      ),
      child: Column(
        children: [
          for (var index = 0; index < rows.length; index++)
            Container(
              padding: const EdgeInsets.symmetric(vertical: 10),
              decoration: BoxDecoration(
                border: index < rows.length - 1
                    ? Border(bottom: BorderSide(color: colors.line))
                    : null,
              ),
              child: rows[index],
            ),
        ],
      ),
    );
  }

  List<Widget> _formRows(BuildContext context) {
    switch (_kind) {
      case 'charge':
        return [
          _field(
            context,
            '充电度数',
            _kwhController,
            hint: '34.2',
            numeric: true,
            helper: _unitPriceHelper,
          ),
          _field(context, '充电站', _placeController, hint: '家里充电桩'),
          _field(
            context,
            '当前里程',
            _odometerController,
            hint: 'km',
            numeric: true,
            helper: _odometerHelper,
          ),
          _field(context, '备注', _noteController, hint: '选填'),
        ];
      case 'fuel':
        return [
          _field(context, '加油站', _placeController, hint: '中石化'),
          _field(
            context,
            '当前里程',
            _odometerController,
            hint: 'km',
            numeric: true,
            helper: _odometerHelper,
          ),
          _field(context, '备注', _noteController, hint: '选填'),
        ];
      case 'mileage':
        return [
          _field(context, '本次里程', _deltaController, hint: 'km', numeric: true),
          _readonly(context, '总里程', _totalOdometerText),
          _field(context, '备注', _noteController, hint: '通勤往返'),
        ];
      case 'parking':
        return [
          _field(context, '地点', _placeController, hint: '商场地库'),
          _field(context, '备注', _noteController, hint: '选填'),
        ];
      case 'toll':
        return [
          _field(context, '路段', _placeController, hint: '选填'),
          _field(context, '备注', _noteController, hint: '选填'),
        ];
      default:
        return [
          _field(context, '保养项目', _noteController, hint: '小保养 · 机油机滤'),
          _field(context, '门店', _placeController, hint: '华迪 4S 店'),
          _field(
            context,
            '当前里程',
            _odometerController,
            hint: 'km',
            numeric: true,
            helper: _odometerHelper,
          ),
        ];
    }
  }

  /// 充电单价自动换算（A32 form 的辅助换算位）：金额 ÷ 度数，两边都填了才出现。
  String? get _unitPriceHelper {
    if (_kind != 'charge') return null;
    final kwh = double.tryParse(_kwhController.text.trim());
    if (kwh == null || kwh <= 0) return null;
    final minor = _amountMinor;
    if (minor <= 0) return null;
    final perKwh = minor / 100 / kwh;
    return '单价自动换算 ¥${perKwh.toStringAsFixed(2)} / kWh';
  }

  /// 里程辅助说明（A32 form）：与档案里的上次里程比，用户不用自己心算。
  String? get _odometerHelper {
    final previous = _profileOdometer;
    final current = _odometerKm;
    if (previous == null || current == null || current == previous) return null;
    final delta = current - previous;
    return delta > 0 ? '较上次 +$delta km' : '比上次少 ${-delta} km';
  }

  /// 记账时刻（只读）：让用户确认这笔落在今天这一刻，不是补录。
  String get _recordedTimeText {
    final now = DateTime.now();
    final sameDay = now.year == _recordedAt.year &&
        now.month == _recordedAt.month &&
        now.day == _recordedAt.day;
    final time =
        '${_recordedAt.hour.toString().padLeft(2, '0')}:${_recordedAt.minute.toString().padLeft(2, '0')}';
    if (sameDay) return '今天 $time';
    return '${_recordedAt.month} 月 ${_recordedAt.day} 日 $time';
  }

  String get _totalOdometerText {
    final delta = int.tryParse(_deltaController.text.trim());
    if (_profileOdometer == null) {
      return delta == null ? '—' : '$delta km';
    }
    return '${_profileOdometer! + (delta ?? 0)} km';
  }

  Widget _field(
    BuildContext context,
    String label,
    TextEditingController controller, {
    String? hint,
    bool numeric = false,
    String? helper,
  }) {
    final colors = context.colors;
    final type = context.typography;
    final row = Row(
      children: [
        SizedBox(
          width: 72,
          child: Text(
            label,
            style: type.sub.copyWith(
              fontSize: 13,
              color: colors.ink2,
              fontWeight: FontWeight.w400,
            ),
          ),
        ),
        Expanded(
          child: TextField(
            controller: controller,
            keyboardType: numeric ? TextInputType.number : TextInputType.text,
            textAlign: TextAlign.right,
            onChanged: (_) => setState(() => _validationMessage = null),
            style: type.rowTitle.copyWith(color: colors.ink),
            decoration: InputDecoration.collapsed(
              hintText: hint,
              hintStyle: type.rowTitle.copyWith(
                color: colors.ink3,
                fontWeight: FontWeight.w400,
              ),
            ),
          ),
        ),
      ],
    );
    if (helper == null) return row;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        row,
        Padding(
          padding: const EdgeInsets.only(top: 3, left: 72),
          child: Text(
            helper,
            textAlign: TextAlign.right,
            style: type.caption.copyWith(color: colors.ink3),
          ),
        ),
      ],
    );
  }

  Widget _readonly(BuildContext context, String label, String value) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      children: [
        SizedBox(
          width: 72,
          child: Text(
            label,
            style: type.sub.copyWith(
              fontSize: 13,
              color: colors.ink2,
              fontWeight: FontWeight.w400,
            ),
          ),
        ),
        Expanded(
          child: Text(
            value,
            textAlign: TextAlign.right,
            style: type.rowTitle.copyWith(
              color: colors.ink3,
              fontWeight: FontWeight.w400,
            ),
          ),
        ),
      ],
    );
  }

  String _kindLabel(String kind) => switch (kind) {
        'charge' => '充电',
        'fuel' => '加油',
        'mileage' => '里程',
        'parking' => '停车',
        'toll' => '过路',
        _ => '保养',
      };

  IconData _kindIcon(String kind) => switch (kind) {
        'charge' => AppIcons.zap,
        'fuel' => AppIcons.fuel,
        'mileage' => AppIcons.gauge,
        'parking' => AppIcons.parking,
        'toll' => AppIcons.ticket,
        _ => AppIcons.wrench,
      };

  Color _kindAccent(BuildContext context, String kind) {
    final colors = context.colors;
    return switch (kind) {
      'charge' => colors.health,
      'fuel' => colors.warm,
      'mileage' => colors.aiBlue,
      'parking' => colors.aiPrimary,
      'toll' => colors.money,
      _ => colors.aiCyan,
    };
  }
}

class _AmountBuffer {
  String _value = '';

  String get text => _value.isEmpty ? '0.00' : _value;

  int get minor {
    if (_value.isEmpty) return 0;
    final parts = _value.split('.');
    final yuan = int.tryParse(parts.first.isEmpty ? '0' : parts.first) ?? 0;
    final centsText = parts.length > 1 ? parts[1] : '';
    final cents = int.tryParse(centsText.padRight(2, '0').substring(0, 2)) ?? 0;
    return yuan * 100 + cents;
  }

  void push(String key) {
    if (key == '.') {
      if (_value.contains('.')) return;
      _value = _value.isEmpty ? '0.' : '$_value.';
      return;
    }
    if (_value.replaceAll('.', '').length >= 8) return;
    if (_value == '0') {
      _value = key;
      return;
    }
    _value = '$_value$key';
  }

  void backspace() {
    if (_value.isEmpty) return;
    _value = _value.substring(0, _value.length - 1);
  }
}
