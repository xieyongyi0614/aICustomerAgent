import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/memory_repository.dart';

/// B6 记忆页：四分组 + 来源追溯 + 用途回执 + 逐条编辑 / 遗忘 + 隐私承诺。
///
/// 分组、标签、来源与类型中文名一律由服务端下发（`API-007` 冻结契约），端上零本地映射。
class MemoryPage extends StatefulWidget {
  const MemoryPage({super.key, this.debugData, this.debugUpdate});

  final MemoryItemsData? debugData;

  /// 测试注入；生产走 `MemoryRepository.updateContent`。
  final Future<MemoryItemData> Function(String id, String content)? debugUpdate;

  @override
  State<MemoryPage> createState() => _MemoryPageState();
}

class _MemoryPageState extends State<MemoryPage> {
  final _repo = MemoryRepository();
  final _editController = TextEditingController();
  MemoryItemsData? _data;
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    final seeded = widget.debugData;
    if (seeded != null) {
      _data = seeded;
      _loading = false;
      return;
    }
    _load();
  }

  @override
  void dispose() {
    _editController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await _repo.listItems();
      if (!mounted) return;
      setState(() {
        _data = data;
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

  void _snack(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _edit(MemoryItemData item) async {
    _editController.text = item.content;
    final next = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('编辑这条记忆'),
        content: TextField(
          controller: _editController,
          autofocus: true,
          maxLines: 4,
          maxLength: 500,
          decoration: const InputDecoration(hintText: '亚丝娜会记住你写下的这句话'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () =>
                Navigator.of(dialogContext).pop(_editController.text.trim()),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    if (next == null || next.isEmpty || next == item.content) return;
    try {
      await (widget.debugUpdate ?? _repo.updateContent)(item.id, next);
    } catch (_) {
      if (!mounted) return;
      _snack('没保存上，检查网络后再试');
      return;
    }
    if (!mounted) return;
    await _load();
  }

  Future<void> _forget(MemoryItemData item) async {
    final colors = context.colors;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('遗忘这条记忆'),
        content: const Text('遗忘后我不会再用它，列表里也不会再出现。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text('遗忘', style: TextStyle(color: colors.danger)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _repo.forget(item.id);
    } catch (_) {
      if (!mounted) return;
      _snack('没删掉，检查网络后再试');
      return;
    }
    if (!mounted) return;
    await _load();
  }

  (Color, Color) _tagColors(BuildContext context, String kind) {
    final colors = context.colors;
    return switch (kind) {
      'preference' => (colors.tagPreferenceBg, colors.tagPreferenceFg),
      'habit' => (colors.tagHabitBg, colors.tagHabitFg),
      'goal' => (colors.tagGoalBg, colors.tagGoalFg),
      _ => (colors.tagRelationBg, colors.tagRelationFg),
    };
  }

  String? _shortDate(String? iso) {
    if (iso == null || iso.isEmpty) return null;
    final parsed = DateTime.tryParse(iso);
    return parsed == null ? null : DateFormat('M/d').format(parsed);
  }

  String _sourceNote(MemoryItemData item) {
    final head = '来源：${item.sourceCount} 次${item.sourceLabel}';
    final stamp = _shortDate(item.lastUpdated);
    return stamp == null ? head : '$head · 最近更新 $stamp';
  }

  Widget _card(BuildContext context, MemoryItemData item) {
    final (bg, fg) = _tagColors(context, item.kind);
    return MemoryCard(
      tagLabel: item.typeLabel,
      tagBg: bg,
      tagFg: fg,
      content: item.content,
      sourceNote: _sourceNote(item),
      usageNote: item.usageReceipts.isEmpty
          ? null
          : item.usageReceipts.map((receipt) => receipt.label).join('、'),
      onEdit: () => _edit(item),
      onForget: () => _forget(item),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final data = _data;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: _loading && data == null
            ? ListView(
                padding: const EdgeInsets.all(18),
                children: const [SkeletonCard(), SkeletonCard()],
              )
            : _error != null && data == null
                ? ErrorState(message: StateCopy.serverError, onRetry: _load)
                : ListView(
                    padding: context.spacing.screenPadding,
                    children: [
                      Text('亚丝娜记住的你', style: type.pageTitle),
                      Text(
                        '${data!.total} 条 · 本周 +${data.addedThisWeek}',
                        style: type.sub.copyWith(color: colors.ink2),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '所有记忆对你完全可见，随时可改、可忘',
                        style: type.sub.copyWith(color: colors.ink2),
                      ),
                      const SizedBox(height: 16),
                      if (data.total == 0)
                        const EmptyState(message: '还没有记住什么，多聊聊就好')
                      else
                        for (final group in data.groups)
                          if (group.items.isNotEmpty) ...[
                            Text(group.label, style: type.sectionTitle),
                            const SizedBox(height: 10),
                            for (final item in group.items) _card(context, item),
                            const SizedBox(height: 14),
                          ],
                      PrivacyNote(
                        child: Text(
                          '记忆是你的资产：全部本地可见、可逐条编辑或遗忘；也可在「我的 · 隐私设置」中一键清空。'
                          '亚丝娜只会用记忆来帮你，不会对你隐瞒。',
                        ),
                      ),
                      const SizedBox(height: 40),
                    ],
                  ),
      ),
    );
  }
}
