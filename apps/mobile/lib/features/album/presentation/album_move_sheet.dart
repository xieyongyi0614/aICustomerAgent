import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../data/album_repository.dart';
import '../domain/album_models.dart';

/// 38/61 「移动到相簿」目标选单：列出全部真实相簿（不含「最近添加」聚合项）。
Future<AlbumBucket?> showAlbumMovePicker(
  BuildContext context,
  AlbumRepository repository,
) {
  return showModalBottomSheet<AlbumBucket>(
    context: context,
    backgroundColor: context.colors.surface,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
    ),
    builder: (context) => _AlbumMovePicker(repository: repository),
  );
}

class _AlbumMovePicker extends StatefulWidget {
  const _AlbumMovePicker({required this.repository});

  final AlbumRepository repository;

  @override
  State<_AlbumMovePicker> createState() => _AlbumMovePickerState();
}

class _AlbumMovePickerState extends State<_AlbumMovePicker> {
  List<AlbumBucket>? _buckets;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final buckets = await widget.repository.buckets();
      if (!mounted) return;
      setState(() => _buckets = buckets.where((b) => !b.isAll).toList());
    } catch (_) {
      if (!mounted) return;
      setState(() => _buckets = const []);
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final buckets = _buckets;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('移动到相簿', style: type.pageTitle.copyWith(fontSize: 18)),
            const SizedBox(height: 4),
            Text(
              '移动由系统相册执行，只在这台手机上生效',
              style: type.caption.copyWith(color: colors.ink3),
            ),
            const SizedBox(height: 12),
            if (buckets == null)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 24),
                child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
              )
            else if (buckets.isEmpty)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 24),
                child: Text(
                  '还没有可用的相簿',
                  style: type.body.copyWith(color: colors.ink2),
                ),
              )
            else
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 320),
                child: ListView(
                  shrinkWrap: true,
                  children: [
                    for (final bucket in buckets)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(
                          bucket.name,
                          style: type.rowTitle.copyWith(fontSize: 14.5),
                        ),
                        trailing: Text(
                          '${bucket.assetCount} 张',
                          style: type.caption.copyWith(
                            fontSize: 11.5,
                            color: colors.ink3,
                            fontFeatures: AppTypography.tabular,
                          ),
                        ),
                        onTap: () => Navigator.of(context).pop(bucket),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
