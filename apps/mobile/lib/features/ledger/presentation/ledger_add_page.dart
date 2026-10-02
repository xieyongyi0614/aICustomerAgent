import 'dart:async';

import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/ledger_repository.dart';

/// B10 #ledgerAdd 手动记账：金额 + 分类 + 备注，备注由 AI 预览分类。
class LedgerAddPage extends StatefulWidget {
  const LedgerAddPage({super.key, this.repository});

  final LedgerRepository? repository;

  @override
  State<LedgerAddPage> createState() => _LedgerAddPageState();
}

class _LedgerAddPageState extends State<LedgerAddPage> {
  static const _previewDebounce = Duration(milliseconds: 320);
  static const _gridLimit = 8;

  late final LedgerRepository _repo = widget.repository ?? LedgerRepository();
  late final String _idempotencyKey =
      'ledger-add-${DateTime.now().microsecondsSinceEpoch}';
  late final DateTime _occurredAt = DateTime.now();

  final _noteController = TextEditingController();
  Timer? _debounce;

  bool _loading = true;
  Object? _error;
  List<LedgerCategoryData> _categories = const [];
  String _direction = 'expense';
  String _amount = '';
  String? _selectedCategoryId;
  LedgerPreviewData? _preview;
  bool _noteEditing = false;
  bool _saving = false;
  bool _saveFailed = false;

  @override
  void initState() {
    super.initState();
    _loadCategories();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _noteController.dispose();
    super.dispose();
  }

  Future<void> _loadCategories() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final rows = await _repo.fetchCategories(kind: _direction);
      if (!mounted) return;
      setState(() {
        _categories = rows.where((row) => row.parentId == null).toList();
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

  int get _amountMinor {
    if (_amount.isEmpty) return 0;
    final parts = _amount.split('.');
    final yuan = int.tryParse(parts.first.isEmpty ? '0' : parts.first) ?? 0;
    final centsText = parts.length > 1 ? parts[1] : '';
    final cents = int.tryParse(centsText.padRight(2, '0').substring(0, 2)) ?? 0;
    return yuan * 100 + cents;
  }

  String get _amountText => _amount.isEmpty ? '0.00' : _amount;

  void _onDirectionChanged(String value) {
    if (value == _direction) return;
    setState(() {
      _direction = value;
      _selectedCategoryId = null;
    });
    _loadCategories();
  }

  void _onKey(String key) {
    if (key == '.') {
      if (_amount.contains('.')) return;
      setState(() => _amount = _amount.isEmpty ? '0.' : '$_amount.');
      return;
    }
    if (_amount.replaceAll('.', '').length >= 8) return;
    if (_amount == '0') {
      setState(() => _amount = key);
      return;
    }
    setState(() => _amount = '$_amount$key');
  }

  void _onBackspace() {
    if (_amount.isEmpty) return;
    setState(() => _amount = _amount.substring(0, _amount.length - 1));
  }

  void _onNoteChanged(String _) {
    _debounce?.cancel();
    _debounce = Timer(_previewDebounce, _refreshPreview);
  }

  Future<void> _refreshPreview() async {
    final note = _noteController.text.trim();
    if (note.isEmpty) {
      if (mounted) setState(() => _preview = null);
      return;
    }
    try {
      final preview = await _repo.classifyPreview(note, kind: _direction);
      if (!mounted) return;
      setState(() => _preview = preview);
    } catch (_) {
      if (!mounted) return;
      setState(() => _preview = null);
    }
  }

  Future<void> _save() async {
    if (_saving || _amountMinor <= 0) return;
    setState(() {
      _saving = true;
      _saveFailed = false;
    });
    try {
      await _repo.createEntry(
        amountMinor: _amountMinor,
        direction: _direction,
        categoryId: _selectedCategoryId,
        occurredAt: _occurredAt,
        note: _noteController.text.trim(),
        idempotencyKey: _idempotencyKey,
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

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    if (_loading) {
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
    if (_error != null) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(child: ErrorState(onRetry: _loadCategories)),
      );
    }
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: context.spacing.screenPadding,
          children: [
            BackLink(label: '记账'),
            const SizedBox(height: 14),
            LedgerSeg(
              value: _direction,
              onChanged: _onDirectionChanged,
              options: const [
                LedgerSegOption(value: 'expense', label: '支出'),
                LedgerSegOption(value: 'income', label: '收入'),
              ],
            ),
            const SizedBox(height: 12),
            LedgerAmount(label: '金额', amountText: _amountText),
            const SizedBox(height: 12),
            LedgerKindGrid(
              items: [
                for (final row in _categories.take(_gridLimit))
                  LedgerKindItem(
                    key: row.id,
                    label: row.name,
                    icon: _iconFor(row.name),
                  ),
              ],
              selectedKey: _selectedCategoryId,
              onSelected: (key) => setState(
                () => _selectedCategoryId =
                    _selectedCategoryId == key ? null : key,
              ),
            ),
            const SizedBox(height: 12),
            LedgerFormRows(
              rows: [
                const LedgerFormRow(label: '账户', value: '零钱'),
                LedgerFormRow(label: '时间', value: _timeLabel(_occurredAt)),
                LedgerFormRow(
                  label: '备注',
                  value: _noteController.text.trim().isEmpty
                      ? null
                      : _noteController.text.trim(),
                  placeholder: '一碗拉面…',
                  onTap: () => setState(() => _noteEditing = !_noteEditing),
                ),
              ],
            ),
            if (_noteEditing) ...[
              const SizedBox(height: 12),
              _noteEditor(),
            ],
            const SizedBox(height: 12),
            AiCard(
              title: 'AI 自动匹配',
              child: Text(
                _previewHint,
                style: context.typography.body.copyWith(color: colors.ink2),
              ),
            ),
            const SizedBox(height: 12),
            LedgerPad(onKey: _onKey, onBackspace: _onBackspace),
            const SizedBox(height: 12),
            if (_saveFailed) ...[
              _saveFailure(),
              const SizedBox(height: 10),
            ],
            LedgerSaveButton(
              label: '保存这一笔',
              enabled: !_saving && _amountMinor > 0,
              onPressed: _save,
            ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  String get _previewHint {
    final preview = _preview;
    if (preview != null && preview.matched) {
      return '我的判断：${preview.categoryName}，下次同类消费直接记住';
    }
    return '写下备注，我会帮你自动匹配分类，下次同类消费直接记住';
  }

  Widget _noteEditor() {
    final colors = context.colors;
    final type = context.typography;
    return Container(
      padding: EdgeInsets.all(context.spacing.cardPadding),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: context.radii.rLg,
      ),
      child: TextField(
        controller: _noteController,
        autofocus: true,
        onChanged: _onNoteChanged,
        style: type.body.copyWith(color: colors.ink),
        decoration: InputDecoration.collapsed(
          hintText: '一碗拉面…',
          hintStyle: type.body.copyWith(color: colors.ink3),
        ),
      ),
    );
  }

  Widget _saveFailure() {
    final colors = context.colors;
    final type = context.typography;
    return Row(
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
        ChipButton(label: StateCopy.retryAction, ghost: true, onTap: _save),
      ],
    );
  }
}

String _timeLabel(DateTime at) {
  final hour = at.hour.toString().padLeft(2, '0');
  final minute = at.minute.toString().padLeft(2, '0');
  return '今天 $hour:$minute';
}

IconData _iconFor(String name) {
  switch (name) {
    case '餐饮':
      return AppIcons.coffee;
    case '交通':
      return AppIcons.train;
    case '购物':
      return AppIcons.wallet;
    case '居住':
      return AppIcons.home;
    case '医疗':
      return AppIcons.activity;
    case '娱乐':
      return AppIcons.sparkles;
    case '学习':
      return AppIcons.book;
    case '人情':
      return AppIcons.heart;
    case '养车':
      return AppIcons.repeat;
    case '工资':
    case '奖金':
    case '其他收入':
      return AppIcons.arrowUp;
    default:
      return AppIcons.wallet;
  }
}
