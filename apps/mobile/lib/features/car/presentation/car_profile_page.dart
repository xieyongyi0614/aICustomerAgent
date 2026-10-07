import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/car_model_catalog_repository.dart';
import '../data/car_repository.dart';
import '../domain/car_model_catalog.dart';
import '../domain/car_models.dart';

/// B16 #carProfile 我的车：身份卡 + 四档案行 + 保养时间线（末行未发生态）。
class CarProfilePage extends StatefulWidget {
  const CarProfilePage({
    super.key,
    this.repository,
    this.catalogRepository,
    this.debugProfile,
  });

  static const subtitle = '你的车辆档案只属于你，可随时查看、修改、删除';

  final CarRepository? repository;
  final CarModelCatalogRepository? catalogRepository;
  final CarProfileData? debugProfile;

  @override
  State<CarProfilePage> createState() => _CarProfilePageState();
}

class _CarProfilePageState extends State<CarProfilePage> {
  late final CarRepository _repo = widget.repository ?? CarRepository();
  late final CarModelCatalogRepository _catalogRepo =
      widget.catalogRepository ?? CarModelCatalogRepository();
  late final Future<CarModelCatalog> _catalogFuture = _catalogRepo.load();
  CarProfileData? _profile;
  bool _loading = true;
  Object? _error;
  bool _editing = false;
  bool _saving = false;
  String? _editError;

  /// 车型预填口径提示：选中车系/版本后告诉用户这个容量从哪来、能不能改。
  String? _batteryHint;

  final _modelController = TextEditingController();
  final _plateController = TextEditingController();
  final _batteryController = TextEditingController();
  final _odometerController = TextEditingController();
  final _chargerController = TextEditingController();
  final _intervalKmController = TextEditingController();
  final _intervalMonthsController = TextEditingController();

  DateTime? _insuranceDue;
  DateTime? _inspectionDue;

  @override
  void initState() {
    super.initState();
    if (widget.debugProfile != null) {
      _profile = widget.debugProfile;
      _loading = false;
      return;
    }
    _load();
  }

  @override
  void dispose() {
    _modelController.dispose();
    _plateController.dispose();
    _batteryController.dispose();
    _odometerController.dispose();
    _chargerController.dispose();
    _intervalKmController.dispose();
    _intervalMonthsController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final profile = await _repo.fetchProfile();
      if (!mounted) return;
      setState(() {
        _profile = profile;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  void _startEditing() {
    final identity = _profile?.identity;
    final files = {for (final row in _profile?.files ?? const <CarFileData>[]) row.key: row};
    _modelController.text = identity?.model ?? '';
    _plateController.text = identity?.plate ?? '';
    _batteryController.text = identity?.batteryKwh?.toString() ?? '';
    _odometerController.text = identity?.odometerKm?.toString() ?? '';
    _insuranceDue = _dateOrNull(files['insurance']?.valueText);
    _inspectionDue = _dateOrNull(files['inspection']?.valueText);
    _chargerController.text = _numberText(files['charger']?.valueText);
    _intervalKmController.text =
        _numberText(files['service_interval']?.valueText);
    _intervalMonthsController.text = '';
    setState(() {
      _editing = true;
      _editError = null;
      _batteryHint = null;
    });
  }

  DateTime? _dateOrNull(String? valueText) {
    if (valueText == null) return null;
    final match = RegExp(r'(\d{4})-(\d{2})-(\d{2})').firstMatch(valueText);
    if (match == null) return null;
    return DateTime(
      int.parse(match.group(1)!),
      int.parse(match.group(2)!),
      int.parse(match.group(3)!),
    );
  }

  String _formatDate(DateTime date) =>
      '${date.year}-${_pad(date.month)}-${_pad(date.day)}';

  String _pad(int value) => value.toString().padLeft(2, '0');

  String _numberText(String? valueText) {
    if (valueText == null) return '';
    final normalized = valueText.replaceAll(',', '');
    final match = RegExp(r'([\d.]+)').firstMatch(normalized);
    if (match == null) return '';
    final raw = match.group(1)!;
    return raw.endsWith('.') ? raw.substring(0, raw.length - 1) : raw;
  }

  Map<String, dynamic> _payload() {
    final payload = <String, dynamic>{};
    void put(String key, String raw, {bool numeric = false}) {
      final text = raw.trim();
      if (text.isEmpty) return;
      payload[key] = numeric ? num.tryParse(text) : text;
    }

    put('model', _modelController.text);
    put('plate', _plateController.text);
    put('battery_kwh', _batteryController.text, numeric: true);
    put('odometer_km', _odometerController.text, numeric: true);
    put('charger_power_kw', _chargerController.text, numeric: true);
    put('service_interval_km', _intervalKmController.text, numeric: true);
    put('service_interval_months', _intervalMonthsController.text, numeric: true);
    if (_insuranceDue != null) {
      payload['insurance_due_at'] = _insuranceDue!.toIso8601String();
    }
    if (_inspectionDue != null) {
      payload['inspection_due_at'] = _inspectionDue!.toIso8601String();
    }
    payload.removeWhere((_, value) => value == null);
    return payload;
  }

  Future<void> _saveEdits() async {
    setState(() {
      _saving = true;
      _editError = null;
    });
    try {
      await _repo.updateProfile(_payload());
      if (!mounted) return;
      setState(() {
        _editing = false;
        _saving = false;
      });
      await _load();
    } on CarProfileValidationException catch (e) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _editError = e.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _editError = StateCopy.networkError;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    if (_loading && _profile == null) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(
          child: ListView(
            padding: const EdgeInsets.all(18),
            children: const [SkeletonCard(), SkeletonCard()],
          ),
        ),
      );
    }
    if (_error != null && _profile == null) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(child: ErrorState(onRetry: _load)),
      );
    }
    final profile = _profile!;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView(
            padding: context.spacing.screenPadding.copyWith(bottom: 40),
            children: [
              BackLink(label: '车辆'),
              Text('我的车', style: type.pageTitle),
              const SizedBox(height: 6),
              Text(
                CarProfilePage.subtitle,
                style: type.caption.copyWith(color: colors.ink3, height: 1.6),
              ),
              const SizedBox(height: 16),
              if (profile.identity == null)
                Text('还没有车辆档案，填一次我就替你记着',
                    style: type.body.copyWith(color: colors.ink2))
              else
                _identityCard(context, profile.identity!),
              const SizedBox(height: 14),
              AiCard(
                title: '亚丝娜的观察',
                actionLabel: '看本月养车账 →',
                onAction: () => context.push('/car'),
                child: Text(
                  _observation(profile),
                  style: type.body
                      .copyWith(color: colors.bodyOnCard, height: 1.65),
                ),
              ),
              const SizedBox(height: 20),
              _SectionTitle(title: '车辆档案', hint: '保养记录我帮你记着'),
              const SizedBox(height: 10),
              if (_editing)
                _editForm(context)
              else
                SettingGroup(
                  children: [
                    for (var i = 0; i < profile.files.length; i++)
                      SettingRow(
                        title: profile.files[i].label,
                        subtitle: profile.files[i].detail,
                        trailing: Text(
                          profile.files[i].valueText,
                          style: type.caption.copyWith(color: colors.ink2),
                        ),
                        icon: _fileIcon(profile.files[i].key),
                        showDivider: i < profile.files.length - 1,
                      ),
                  ],
                ),
              const SizedBox(height: 10),
              if (!_editing)
                LedgerSaveButton(
                  label: profile.identity == null ? '填写车辆档案' : '改档案',
                  ghost: profile.identity != null,
                  elevated: false,
                  onPressed: _startEditing,
                ),
              const SizedBox(height: 20),
              _SectionTitle(
                title: '保养记录',
                hint: _editing ? null : '${_recordCount(profile)} 次',
              ),
              const SizedBox(height: 10),
              if (profile.services.isEmpty)
                Text('还没有保养记录', style: type.body.copyWith(color: colors.ink2))
              else
                Timeline(
                  items: [
                    for (var i = 0; i < profile.services.length; i++)
                      TimelineItem(
                        icon: profile.services[i].upcoming
                            ? AppIcons.clock
                            : AppIcons.wrench,
                        accent: colors.health,
                        title: profile.services[i].title,
                        subtitle: _serviceSubtitle(profile.services[i]),
                        valueText: _serviceValue(profile.services[i]),
                        isUpcoming: profile.services[i].upcoming,
                      ),
                  ],
                ),
              const SizedBox(height: 16),
              PrivacyNote(
                child: Text(
                  carLinkageHintFallback,
                  style: type.caption.copyWith(color: colors.ink2, height: 1.6),
                ),
              ),
              if (profile.restrictionGuide != null) ...[
                const SizedBox(height: 10),
                Text(
                  profile.restrictionGuide!,
                  style: type.caption.copyWith(color: colors.ink3),
                ),
              ],
              const SizedBox(height: 18),
              LedgerSaveButton(
                label: '＋ 记一次保养',
                onPressed: () async {
                  await context.push<bool>('/car/add?kind=service');
                  if (!mounted) return;
                  await _load();
                },
              ),
            ],
          ),
        ),
      ),
    );
  }

  int _recordCount(CarProfileData profile) =>
      profile.services.where((row) => !row.upcoming).length;

  String _observation(CarProfileData profile) {
    final identity = profile.identity;
    if (identity == null) return '把车型和保养周期填上，我就能替你算下次该做什么。';
    final parts = <String>[];
    if (identity.ageText != null) parts.add('这辆车 ${identity.ageText}');
    if (identity.odometerKm != null) {
      parts.add('总里程 ${identity.odometerKm} km');
    }
    if (profile.reminders.isNotEmpty) {
      parts.add('有 ${profile.reminders.length} 件事我会提前提醒你');
    }
    return parts.isEmpty ? '档案还差几项，补齐后我替你盯。' : '${parts.join('，')}。';
  }

  String? _serviceSubtitle(CarServiceRowData row) {
    if (row.upcoming) return '还没发生，到点我会提醒你';
    final parts = <String>[
      if (row.occurredAt != null) _shortDate(row.occurredAt!),
      if (row.odometerKm != null) '${row.odometerKm} km',
      if (row.place != null) row.place!,
    ];
    return parts.isEmpty ? null : parts.join(' · ');
  }

  String _serviceValue(CarServiceRowData row) {
    if (row.upcoming) {
      if (row.dueKm != null) return '${row.dueKm} km';
      return '待排期';
    }
    if (row.amountMinor == null) return '免费';
    return '¥${row.amountText ?? (row.amountMinor! / 100).toStringAsFixed(2)}';
  }

  IconData _fileIcon(String key) => switch (key) {
        'insurance' => AppIcons.shield,
        'inspection' => AppIcons.calendar,
        'charger' => AppIcons.batteryCharging,
        _ => AppIcons.repeat,
      };

  Widget _identityCard(BuildContext context, CarIdentityData identity) {
    final colors = context.colors;
    final type = context.typography;
    return Container(
      padding: EdgeInsets.all(context.spacing.cardPadding),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: context.radii.rLg,
        boxShadow: context.elevation.card,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  identity.model ?? '未命名车型',
                  style: type.title.copyWith(fontSize: 17),
                ),
              ),
              if (identity.plate != null)
                Container(
                  padding:
                      const EdgeInsets.symmetric(vertical: 4, horizontal: 9),
                  decoration: BoxDecoration(
                    color: colors.aiBlue.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    identity.plate!,
                    style: type.caption.copyWith(
                      color: colors.aiBlue,
                      fontWeight: FontWeight.w700,
                      letterSpacing: 0.2,
                    ),
                  ),
                ),
            ],
          ),
          if (identity.trimNote != null) ...[
            const SizedBox(height: 5),
            Text(
              identity.trimNote!,
              style: type.caption.copyWith(color: colors.ink3),
            ),
          ],
          const SizedBox(height: 14),
          Row(
            children: [
              Expanded(
                child: _metric(
                  context,
                  '电池容量',
                  identity.batteryKwh == null
                      ? '—'
                      : '${identity.batteryKwh!.toStringAsFixed(1)} kWh',
                ),
              ),
              Expanded(child: _metric(context, '车龄', identity.ageText ?? '—')),
              Expanded(
                child: _metric(
                  context,
                  '总里程',
                  identity.odometerKm == null
                      ? '—'
                      : '${identity.odometerKm} km',
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _metric(BuildContext context, String label, String value) {
    final colors = context.colors;
    final type = context.typography;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: type.caption.copyWith(color: colors.ink3)),
        const SizedBox(height: 3),
        Text(
          value,
          style: type.numeric(type.rowTitle).copyWith(fontSize: 14),
        ),
      ],
    );
  }

  Widget _editForm(BuildContext context) {
    final colors = context.colors;
    return Column(
      children: [
        _box(
          context,
          [
            _modelRow(context),
            _plateRow(context),
            _numberRow(
              context,
              '电池容量',
              _batteryController,
              hint: '85.4',
              unit: 'kWh',
              decimal: true,
            ),
            _numberRow(
              context,
              '总里程',
              _odometerController,
              hint: '12480',
              unit: 'km',
            ),
          ],
        ),
        const SizedBox(height: 6),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 2),
          child: Text(
            _batteryHint ?? '车型支持搜索，日期点开滚轮选，不用手打。',
            style: context.typography.caption
                .copyWith(color: context.colors.ink3),
          ),
        ),
        const SizedBox(height: 12),
        _box(
          context,
          [
            _dateRow(
              context,
              '保险到期',
              _insuranceDue,
              (value) => setState(() => _insuranceDue = value),
            ),
            _dateRow(
              context,
              '年检到期',
              _inspectionDue,
              (value) => setState(() => _inspectionDue = value),
            ),
            _numberRow(
              context,
              '充电桩功率',
              _chargerController,
              hint: '7',
              unit: 'kW',
              decimal: true,
            ),
            _numberRow(
              context,
              '保养周期里程',
              _intervalKmController,
              hint: '10000',
              unit: 'km',
            ),
            _numberRow(
              context,
              '保养周期月数',
              _intervalMonthsController,
              hint: '12',
              unit: '个月',
            ),
          ],
        ),
        if (_editError != null) ...[
          const SizedBox(height: 8),
          Text(
            _editError!,
            style: context.typography.caption.copyWith(
              color: colors.danger,
              fontWeight: FontWeight.w400,
            ),
          ),
        ],
        const SizedBox(height: 12),
        Row(
          children: [
            Expanded(
              child: LedgerSaveButton(
                label: '取消',
                ghost: true,
                onPressed: () => setState(() => _editing = false),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: LedgerSaveButton(
                label: '保存档案',
                enabled: !_saving,
                elevated: false,
                onPressed: _saveEdits,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _box(BuildContext context, List<Widget> rows) {
    final colors = context.colors;
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
              padding: const EdgeInsets.symmetric(vertical: 12),
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

  Widget _modelRow(BuildContext context) {
    final value = _modelController.text.trim();
    return _selectRow(
      context,
      key: const ValueKey('car-profile-field-model'),
      label: '车型',
      value: value.isEmpty ? null : value,
      placeholder: '选车型',
      onTap: _pickModel,
    );
  }

  Future<void> _pickModel() async {
    final catalog = await _catalogFuture;
    if (!mounted) return;
    final picked = await showChoiceSheet<_ModelPick>(
      context: context,
      title: '选车型',
      searchable: true,
      searchHint: '搜品牌或车系，找不到就直接写',
      freeTextBuilder: _ModelFreeText.new,
      items: [
        for (final option in catalog.models)
          ChoiceSheetItem(
            value: _ModelSeries(option),
            label: option.series,
            group: option.brand,
            note: option.powertrain.label,
          ),
      ],
    );
    if (!mounted) return;
    switch (picked) {
      case null:
        return;
      case _ModelFreeText(:final text):
        setState(() {
          _modelController.text = text;
          _batteryHint = '目录里没有这个车系，电池容量按购车资料填就好。';
        });
      case _ModelSeries(:final option):
        await _pickVariant(option);
    }
  }

  Future<void> _pickVariant(CarModelOption option) async {
    final variants = option.variants;
    CarModelVariant? variant;
    if (variants.length == 1) {
      variant = variants.first;
    } else if (variants.length > 1) {
      variant = await showChoiceSheet<CarModelVariant>(
        context: context,
        title: '选「${option.series}」的版本',
        items: [
          for (final item in variants)
            ChoiceSheetItem(
              value: item,
              label: item.name,
              note: item.batteryKwh == null
                  ? null
                  : '${_formatKwh(item.batteryKwh!)} kWh',
            ),
        ],
      );
      if (!mounted || variant == null) return;
    }

    final battery = variant?.batteryKwh;
    setState(() {
      _modelController.text = option.name;
      // 选车型是明确意图：带得出容量的直接覆盖预填（提示写明是参考值，可改）；
      // 没有容量数据时不动用户已经填的值。
      if (battery != null) _batteryController.text = _formatKwh(battery);
      _batteryHint = _hintFor(option, variant);
    });
  }

  String _hintFor(CarModelOption option, CarModelVariant? variant) {
    final battery = variant?.batteryKwh;
    if (battery != null && variant != null) {
      return '已按「${variant.name}」预填 ${_formatKwh(battery)} kWh，参考值可改。';
    }
    if (option.powertrain == CarPowertrain.fuel) {
      return '「${option.name}」是燃油车，电池容量留空就行。';
    }
    return '「${option.name}」还没有电池容量数据，按购车资料填就好。';
  }

  String _formatKwh(double value) =>
      value == value.roundToDouble() ? value.toStringAsFixed(0) : '$value';

  Widget _plateRow(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return _rowShell(
      context,
      label: '车牌',
      trailing: TextField(
        controller: _plateController,
        textAlign: TextAlign.right,
        textCapitalization: TextCapitalization.characters,
        style: type.rowTitle.copyWith(color: colors.ink),
        decoration: InputDecoration.collapsed(
          hintText: '沪 A·D8F2K',
          hintStyle: type.rowTitle.copyWith(
            color: colors.ink3,
            fontWeight: FontWeight.w400,
          ),
        ),
      ),
    );
  }

  Widget _numberRow(
    BuildContext context,
    String label,
    TextEditingController controller, {
    String? hint,
    String? unit,
    bool decimal = false,
  }) {
    final colors = context.colors;
    final type = context.typography;
    return _rowShell(
      context,
      label: label,
      trailing: Row(
        children: [
          Flexible(
            child: TextField(
              controller: controller,
              textAlign: TextAlign.right,
              keyboardType: TextInputType.numberWithOptions(decimal: decimal),
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
          if (unit != null) ...[
            const SizedBox(width: 4),
            Text(unit, style: type.caption.copyWith(color: colors.ink3)),
          ],
        ],
      ),
    );
  }

  Widget _dateRow(
    BuildContext context,
    String label,
    DateTime? value,
    ValueChanged<DateTime?> onChanged,
  ) {
    return _selectRow(
      context,
      key: ValueKey('car-profile-field-$label'),
      label: label,
      value: value == null ? null : _formatDate(value),
      placeholder: '选择日期',
      onTap: () async {
        final picked = await showDateWheelSheet(
          context: context,
          title: label,
          initial: value,
        );
        if (picked == null || !mounted) return;
        onChanged(picked);
      },
      onClear: value == null ? null : () => onChanged(null),
    );
  }

  Widget _rowShell(
    BuildContext context, {
    required String label,
    required Widget trailing,
  }) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      children: [
        SizedBox(
          width: 84,
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
          child: Align(
            alignment: Alignment.centerRight,
            child: trailing,
          ),
        ),
      ],
    );
  }

  Widget _selectRow(
    BuildContext context, {
    Key? key,
    required String label,
    required String placeholder,
    required VoidCallback onTap,
    String? value,
    VoidCallback? onClear,
  }) {
    final colors = context.colors;
    final type = context.typography;
    final filled = value != null && value.isNotEmpty;
    return GestureDetector(
      key: key,
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Row(
        children: [
          SizedBox(
            width: 84,
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
            child: Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                Flexible(
                  child: Text(
                    filled ? value : placeholder,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.right,
                    style: type.rowTitle.copyWith(
                      color: filled ? colors.ink : colors.ink3,
                      fontWeight: filled ? FontWeight.w600 : FontWeight.w400,
                    ),
                  ),
                ),
                if (onClear != null) ...[
                  const SizedBox(width: 6),
                  GestureDetector(
                    onTap: onClear,
                    behavior: HitTestBehavior.opaque,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 4,
                        vertical: 6,
                      ),
                      child: Icon(AppIcons.x, size: 14, color: colors.ink3),
                    ),
                  ),
                ],
                const SizedBox(width: 6),
                Icon(AppIcons.chevronRight, size: 15, color: colors.ink3),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

String _shortDate(String iso) {
  if (iso.length < 10) return iso;
  return iso.substring(0, 10);
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, this.hint});

  final String title;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      children: [
        Text(title, style: type.sectionTitle),
        const Spacer(),
        if (hint != null)
          Text(hint!, style: type.caption.copyWith(color: colors.ink3)),
      ],
    );
  }
}

/// 车型选择结果：目录里的车系（带版本与参数），或用户自己写的车型名。
sealed class _ModelPick {
  const _ModelPick();
}

class _ModelSeries extends _ModelPick {
  const _ModelSeries(this.option);

  final CarModelOption option;
}

class _ModelFreeText extends _ModelPick {
  const _ModelFreeText(this.text);

  final String text;
}
