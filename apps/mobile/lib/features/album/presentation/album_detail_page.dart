import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import 'album_manage_page.dart';
import '../data/album_repository.dart';
import '../domain/album_models.dart';

/// B18 #albumDetail 相簿详情：按拍摄日期分组、视频带时长徽章。
///
/// ✦ 徽章只在存在真实判定时出现（D16：相似连拍本期未开启 → 页内无 ✦）。
class AlbumDetailPage extends StatefulWidget {
  const AlbumDetailPage({
    super.key,
    this.repository,
    this.albumId,
    this.albumName,
    this.preloaded,
  });

  final AlbumRepository? repository;
  final String? albumId;
  final String? albumName;

  final AlbumManageData? preloaded;

  @override
  State<AlbumDetailPage> createState() => _AlbumDetailPageState();
}

class _AlbumDetailPageState extends State<AlbumDetailPage> {
  late final AlbumRepository _repo = widget.repository ?? AlbumRepository();
  bool _loading = true;
  List<PhotoAsset> _assets = [];
  Map<String, ImageProvider?> _thumbs = {};

  @override
  void initState() {
    super.initState();
    _begin();
  }

  Future<void> _begin() async {
    setState(() => _loading = true);
    final preloaded = widget.preloaded;
    if (preloaded != null) {
      setState(() {
        _assets = preloaded.assets;
        _thumbs = preloaded.thumbnails;
        _loading = false;
      });
      return;
    }
    final albumId = widget.albumId;
    if (albumId == null) {
      setState(() => _loading = false);
      return;
    }
    final page = await _repo.assets(bucketId: albumId, start: 0, limit: 200);
    final thumbs = <String, ImageProvider?>{};
    for (final asset in page.items) {
      try {
        thumbs[asset.id] = await _repo.source.thumbnailProvider(asset);
      } catch (_) {
        thumbs[asset.id] = null;
      }
    }
    if (!mounted) return;
    setState(() {
      _assets = page.items;
      _thumbs = thumbs;
      _loading = false;
    });
  }

  Map<String, List<PhotoAsset>> get _groupByDay {
    final formatter = DateFormat('yyyy 年 M 月 d 日');
    final groups = <String, List<PhotoAsset>>{};
    for (final asset in _assets) {
      groups.putIfAbsent(formatter.format(asset.takenAt), () => []).add(asset);
    }
    return groups;
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final name = widget.albumName ?? '相簿';
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
    final groups = _groupByDay;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: ListView(
          padding: context.spacing.screenPadding.copyWith(bottom: 40),
          children: [
            BackLink(label: '相册'),
            const SizedBox(height: 10),
            Text(name, style: type.pageTitle),
            Text(
              '${_assets.length} 张 · 本机自动归类 · 只存在这台手机上',
              style: type.caption.copyWith(fontSize: 12, color: colors.ink2),
            ),
            for (final entry in groups.entries) ...[
              const SizedBox(height: 16),
              Row(
                children: [
                  Text(
                    entry.key,
                    style: type.sectionTitle.copyWith(fontSize: 14),
                  ),
                  const Spacer(),
                  Text(
                    '${entry.value.length} 张',
                    style: type.caption.copyWith(fontSize: 11.5, color: colors.ink3),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              GridView.builder(
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: PhotoTile.gridCrossAxisCount,
                  crossAxisSpacing: PhotoTile.gridSpacing,
                  mainAxisSpacing: PhotoTile.gridSpacing,
                  childAspectRatio: 1,
                ),
                itemCount: entry.value.length,
                itemBuilder: (context, index) {
                  final asset = entry.value[index];
                  return PhotoTile(
                    thumbnail: _thumbs[asset.id],
                    durationText: asset.duration == null
                        ? null
                        : _format(asset.duration!),
                    onTap: () =>
                        context.push('/album/photo?id=${Uri.encodeComponent(asset.id)}'),
                  );
                },
              ),
            ],
          ],
        ),
      ),
    );
  }

  String _format(Duration d) {
    final minutes = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final seconds = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }
}
