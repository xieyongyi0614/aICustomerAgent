import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/cards.dart';
import '../../../design_system/components/components.dart';
import '../data/memory_repository.dart';

/// B6 记忆页：分组 + 来源追溯 + 用途回执 + 隐私承诺。
class MemoryPage extends StatefulWidget {
  const MemoryPage({super.key, this.debugItems});

  final List<MemoryItemData>? debugItems;

  @override
  State<MemoryPage> createState() => _MemoryPageState();
}

class _MemoryPageState extends State<MemoryPage> {
  final _repo = MemoryRepository();
  List<MemoryItemData> _items = [];
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    if (widget.debugItems != null) {
      _items = widget.debugItems!;
      _loading = false;
      return;
    }
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final items = await _repo.listItems();
      if (!mounted) return;
      setState(() {
        _items = items;
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

  (Color, Color) _tagColors(BuildContext context, String kind) {
    final colors = context.colors;
    return switch (kind) {
      'preference' => (colors.tagPreferenceBg, colors.tagPreferenceFg),
      'habit' => (colors.tagHabitBg, colors.tagHabitFg),
      'goal' => (colors.tagGoalBg, colors.tagGoalFg),
      'relation' => (colors.tagRelationBg, colors.tagRelationFg),
      _ => (colors.tagPreferenceBg, colors.tagPreferenceFg),
    };
  }

  String _tagLabel(String kind) => switch (kind) {
        'preference' => '偏好',
        'habit' => '习惯',
        'goal' => '目标',
        'relation' => '关系',
        _ => '记忆',
      };

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: _loading && _items.isEmpty
            ? const ListView(
                padding: EdgeInsets.all(18),
                children: [SkeletonCard(), SkeletonCard()],
              )
            : _error != null && _items.isEmpty
                ? ErrorState(message: StateCopy.serverError, onRetry: _load)
                : ListView(
                    padding: context.spacing.screenPadding,
                    children: [
                      Text('亚丝娜记住的你', style: type.pageTitle),
                      Text(
                        '${_items.length} 条 · 每条都能看到来源，也可以随时遗忘',
                        style: type.sub.copyWith(color: colors.ink2),
                      ),
                      const SizedBox(height: 16),
                      if (_items.isEmpty)
                        const EmptyState(message: '还没有记住什么，多聊聊就好')
                      else
                        for (final item in _items)
                          Builder(
                            builder: (context) {
                              final (bg, fg) = _tagColors(context, item.kind);
                              return MemoryCard(
                                tagLabel: _tagLabel(item.kind),
                                tagBg: bg,
                                tagFg: fg,
                                content: item.content,
                                sourceNote:
                                    '来源：${item.sourceCount ?? 1} 次对话提及'
                                    '${item.lastUpdated == null ? '' : ' · 最近更新 ${item.lastUpdated!.substring(0, 10)}'}',
                                usageNote: item.usageReceipts.isEmpty
                                    ? null
                                    : '已用于${item.usageReceipts.join('、')}',
                                onEdit: () => _repo.updateContent(item.id, item.content),
                                onForget: () async {
                                  await _repo.forget(item.id);
                                  await _load();
                                },
                              );
                            },
                          ),
                      PrivacyNote(
                        child: Text(
                          '这些记忆只存在你的账户里，用来让我更懂你。你可以随时编辑或遗忘任何一条。',
                        ),
                      ),
                      const SizedBox(height: 40),
                    ],
                  ),
      ),
    );
  }
}
