import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/album_analysis.dart';
import '../data/album_repository.dart';
import '../domain/album_models.dart';

/// B15 #albumManage 批量管理：AI 预选可逐张推翻、删除走系统「最近删除」。
///
/// 相似连拍本期未开启（D16）：呈诚实未支持态，不参与任何计数。
class AlbumManagePage extends StatefulWidget {
  const AlbumManagePage({
    super.key,
    this.repository,
    this.analyzer,
    this.preloaded,
  });

  final AlbumRepository? repository;
  final AlbumAnalyzer? analyzer;

  /// 测试注入：跳过扫描直接呈现这些资产与建议。
  final AlbumManageData? preloaded;

  @override
  State<AlbumManagePage> createState() => _AlbumManagePageState();
}

/// 页面数据快照（测试替身友好）。
class AlbumManageData {
  const AlbumManageData({
    required this.assets,
    required this.thumbnails,
    required this.preselectedIds,
    required this.totalCount,
  });

  final List<PhotoAsset> assets;
  final Map<String, ImageProvider?> thumbnails;
  final Set<String> preselectedIds;
  final int totalCount;
}

class _AlbumManagePageState extends State<AlbumManagePage> {
  late final AlbumRepository _repo = widget.repository ?? AlbumRepository();
  late final AlbumAnalyzer _analyzer =
      widget.analyzer ?? const AlbumAnalyzer();

  AlbumManageData? _data;
  bool _loading = true;
  Set<String> _selected = {};
  Map<String, bool> _overrides = {};

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
        _data = preloaded;
        _selected = {...preloaded.preselectedIds};
        _loading = false;
      });
      return;
    }
    final snapshots = await _repo.scanSnapshots();
    if (!mounted) return;
    if (snapshots == null) {
      setState(() => _loading = false);
      return;
    }
    final result = await _analyzer.analyze(snapshots);
    final preselected = <String>{};
    for (final section in result.sections) {
      if (section.supported) {
        preselected.addAll(section.suggestion?.assetIds ?? const []);
      }
    }
    final overrides = await _repo.store.loadOverrides();
    final assets = await _collectAssets(preselected.length);
    final thumbnails = <String, ImageProvider?>{};
    for (final asset in assets) {
      try {
        thumbnails[asset.id] = await _repo.source.thumbnailProvider(asset);
      } catch (_) {
        thumbnails[asset.id] = null;
      }
    }

    if (!mounted) return;
    setState(() {
      _data = AlbumManageData(
        assets: assets,
        thumbnails: thumbnails,
        preselectedIds: preselected,
        totalCount: snapshots.length,
      );
      _overrides = overrides;
      _selected = {...preselected};
      _loading = false;
    });
  }

  Future<List<PhotoAsset>> _collectAssets(int hint) async {
    final assets = <PhotoAsset>[];
    var start = 0;
    while (true) {
      final page = await _repo.assets(start: start, limit: 120);
      assets.addAll(page.items);
      if (!page.hasMore || page.items.isEmpty) break;
      start += page.items.length;
      if (assets.length > 2000) break;
    }
    return assets;
  }

  void _toggle(String id) {
    setState(() {
      final keep = !_selected.remove(id);
      if (keep) _selected.add(id);
      _repo.store.saveOverride(id, keep);
      _overrides[id] = keep;
    });
  }

  Future<void> _deleteSelected() async {
    final data = _data;
    if (data == null || _selected.isEmpty) return;
    final count = _selected.length;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        content: Text('删除选中的 $count 张照片？删除后进系统「最近删除」，30 天内可恢复。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('先不了'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    for (final id in _selected.toList()) {
      final asset = data.assets.firstWhere((a) => a.id == id);
      await _repo.moveToTrash(asset);
    }
    if (!mounted) return;
    setState(() {
      _selected.clear();
      _begin();
    });
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final data = _data;
    if (_loading || data == null) {
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
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 12, 18, 0),
              child: Row(
                children: [
                  BackLink(
                    label: '取消',
                    onTap: () => Navigator.of(context).maybePop(),
                  ),
                  Expanded(
                    child: Text(
                      '已选 ${_selected.length} 张',
                      textAlign: TextAlign.center,
                      style: type.caption.copyWith(
                        fontSize: 15.5,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  const SizedBox(width: 60),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 8, 18, 0),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text(
                  '亚丝娜已帮你预选，逐张可推翻；推翻会被记住',
                  style: type.caption.copyWith(fontSize: 12, color: colors.ink2),
                ),
              ),
            ),
            Expanded(
              child: GridView.builder(
                padding: const EdgeInsets.all(18),
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: PhotoTile.gridCrossAxisCount,
                  crossAxisSpacing: PhotoTile.gridSpacing,
                  mainAxisSpacing: PhotoTile.gridSpacing,
                  childAspectRatio: 1,
                ),
                itemCount: data.assets.length,
                itemBuilder: (context, index) {
                  final asset = data.assets[index];
                  final selected = _selected.contains(asset.id);
                  return PhotoTile(
                    thumbnail: data.thumbnails[asset.id],
                    selectionMode: true,
                    selected: selected,
                    onToggle: () => _toggle(asset.id),
                  );
                },
              ),
            ),
            AlbumActionBar(
              actions: [
                AlbumAction(
                  label: '删除 ${_selected.length} 张',
                  icon: AppIcons.trash,
                  danger: true,
                  onTap: _deleteSelected,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
