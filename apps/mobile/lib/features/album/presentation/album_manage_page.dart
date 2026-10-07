import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/album_analysis.dart';
import '../data/album_repository.dart';
import '../domain/album_models.dart';
import 'album_move_sheet.dart';

/// B15 #albumManage 批量管理：AI 预选可逐张推翻、删除走系统「最近删除」。
///
/// 分组呈现（38）：过期截图 / 重复保存为 AI 预选组，其余落「手动挑选」；
/// 相似连拍本期未开启（D16）→ 只呈诚实未支持说明，不参与任何计数。
class AlbumManagePage extends StatefulWidget {
  const AlbumManagePage({
    super.key,
    this.repository,
    this.analyzer,
    this.preloaded,
    this.bucketId,
    this.bucketName,
  });

  final AlbumRepository? repository;
  final AlbumAnalyzer? analyzer;

  /// 测试注入：跳过扫描直接呈现这些资产与建议。
  final AlbumManageData? preloaded;

  /// 从相簿详情（60）进入时限定该相簿；空 = 全部照片流。
  final String? bucketId;
  final String? bucketName;

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
    this.sections = const [],
  });

  final List<PhotoAsset> assets;
  final Map<String, ImageProvider?> thumbnails;
  final Set<String> preselectedIds;
  final int totalCount;

  /// 分析结果（决定分组与 AI 提示条；空 = 无分析，全部落手动挑选组）。
  final List<AlbumAnalysisSection> sections;
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
    final snapshots = await _repo.scanSnapshots(bucketId: widget.bucketId);
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
    final viewAssetIds = {for (final asset in assets) asset.id};
    final preselectedInView = preselected.intersection(viewAssetIds);
    final thumbnails = <String, ImageProvider?>{};
    for (var start = 0; start < assets.length; start += _thumbnailBatch) {
      final batch = assets.sublist(
        start,
        (start + _thumbnailBatch).clamp(0, assets.length),
      );
      final loaded = await Future.wait([
        for (final asset in batch) _thumbnailOf(asset),
      ]);
      for (var i = 0; i < batch.length; i++) {
        thumbnails[batch[i].id] = loaded[i];
      }
    }

    if (!mounted) return;
    setState(() {
      _data = AlbumManageData(
        assets: assets,
        thumbnails: thumbnails,
        preselectedIds: preselectedInView,
        totalCount: snapshots.length,
        sections: result.sections,
      );
      _overrides = overrides;
      _selected = {...preselectedInView};
      _loading = false;
    });
  }

  /// 缩略图按批并发取：逐张串行在数千张时会把主 isolate 卡死。
  static const _thumbnailBatch = 16;

  Future<ImageProvider?> _thumbnailOf(PhotoAsset asset) async {
    try {
      return await _repo.source.thumbnailProvider(asset);
    } catch (_) {
      return null;
    }
  }

  Future<List<PhotoAsset>> _collectAssets(int hint) async {
    final assets = <PhotoAsset>[];
    var start = 0;
    while (true) {
      final page = await _repo.assets(
        bucketId: widget.bucketId,
        start: start,
        limit: 120,
      );
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

  bool get _allSelected {
    final data = _data;
    return data != null &&
        data.assets.isNotEmpty &&
        _selected.length == data.assets.length;
  }

  void _toggleSelectAll() {
    final data = _data;
    if (data == null) return;
    setState(() {
      if (_allSelected) {
        _selected.clear();
      } else {
        _selected = {for (final asset in data.assets) asset.id};
      }
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
    final byId = _assetsById(data);
    for (final id in _selected.toList()) {
      final asset = byId[id];
      if (asset == null) continue;
      await _repo.moveToTrash(asset);
    }
    if (!mounted) return;
    setState(() => _selected.clear());
    unawaited(_begin());
  }

  Future<void> _moveSelected() async {
    final data = _data;
    if (data == null || _selected.isEmpty || !mounted) return;
    final target = await showAlbumMovePicker(context, _repo);
    if (target == null || !mounted) return;
    var moved = 0;
    final byId = _assetsById(data);
    final selectedCount = _selected.length;
    for (final id in _selected.toList()) {
      final asset = byId[id];
      if (asset == null) continue;
      if (await _repo.moveToAlbum(asset, target)) moved++;
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          moved == selectedCount
              ? '已移动 $moved 张到「${target.name}」'
              : '移动了 $moved 张，其余这张设备不支持移动',
        ),
      ),
    );
    setState(() {});
    unawaited(_begin());
  }

  /// 全库分析结果可能含有本次视口（>2000 截断）之外的预选 id，
  /// 删除/移动只能按视口内的资产查找，找不到就跳过，绝不 firstWhere 抛异常。
  Map<String, PhotoAsset> _assetsById(AlbumManageData data) =>
      {for (final asset in data.assets) asset.id: asset};

  void _tagSelected() {
    if (_selected.isEmpty) return;
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        content: const Text('照片标签依赖系统能力，这台设备本期未开启。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('知道了'),
          ),
        ],
      ),
    );
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
                  BackLink(label: '取消'),
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
                  GestureDetector(
                    onTap: _toggleSelectAll,
                    behavior: HitTestBehavior.opaque,
                    child: Text(
                      _allSelected ? '全不选' : '全选',
                      style: type.caption.copyWith(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: colors.aiBlue,
                      ),
                    ),
                  ),
                ],
              ),
            ),
            if (data.preselectedIds.isNotEmpty) ...[
              const SizedBox(height: 10),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 18),
                child: MemHint(text: _preselectHint(data)),
              ),
            ],
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 8, 18, 0),
              child: Align(
                alignment: Alignment.centerLeft,
                child: GestureDetector(
                  onTap: () => context.push('/album/ai'),
                  behavior: HitTestBehavior.opaque,
                  child: Text(
                    '这些预选是怎么算出来的 →',
                    style: type.caption.copyWith(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: colors.aiBlue,
                    ),
                  ),
                ),
              ),
            ),
            Expanded(child: _groupedGrid(data)),
            AlbumActionBar(
              actions: [
                AlbumAction(
                  label: '移动',
                  icon: AppIcons.move,
                  onTap: _selected.isEmpty ? null : _moveSelected,
                ),
                AlbumAction(
                  label: '加标签',
                  icon: AppIcons.tag,
                  onTap: _selected.isEmpty ? null : _tagSelected,
                ),
                AlbumAction(
                  label: '删除 ${_selected.length} 张',
                  icon: AppIcons.trash,
                  danger: true,
                  onTap: _selected.isEmpty ? null : _deleteSelected,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _preselectHint(AlbumManageData data) {
    final parts = <String>[];
    for (final section in data.sections) {
      final suggestion = section.suggestion;
      if (!section.supported || suggestion == null) continue;
      final ids = suggestion.assetIds
          .where((id) => data.preselectedIds.contains(id))
          .length;
      if (ids == 0) continue;
      parts.add('$ids 张${_kindLabel(section.kind)}');
    }
    if (parts.isEmpty) {
      return '已帮你预选 ${data.preselectedIds.length} 张，都在本机分析';
    }
    return '已帮你预选 ${data.preselectedIds.length} 张：'
        '${parts.join(' + ')}，都在本机分析';
  }

  String _kindLabel(AlbumSuggestionKind kind) => switch (kind) {
        AlbumSuggestionKind.expiredScreenshots => '过期截图',
        AlbumSuggestionKind.duplicateSaves => '重复保存',
        AlbumSuggestionKind.similarBursts => '相似连拍',
      };

  Widget _groupedGrid(AlbumManageData data) {
    final unsupported = data.sections
        .where((s) => !s.supported)
        .map((s) => s.unsupportedReason ?? '')
        .where((reason) => reason.isNotEmpty)
        .toList();
    final grouped = <String, Set<String>>{};
    for (final section in data.sections) {
      final suggestion = section.suggestion;
      if (!section.supported || suggestion == null) continue;
      grouped[_kindLabel(section.kind)] = suggestion.assetIds.toSet();
    }
    final claimed = <String>{for (final ids in grouped.values) ...ids};
    final slivers = <Widget>[];
    grouped.forEach((label, ids) {
      final assets =
          data.assets.where((asset) => ids.contains(asset.id)).toList();
      if (assets.isEmpty) return;
      slivers
        ..add(_groupLabelSliver('$label · 共 ${assets.length} 张（AI 预选）'))
        ..add(_gridSliver(data, assets));
    });
    final manual =
        data.assets.where((asset) => !claimed.contains(asset.id)).toList();
    if (manual.isNotEmpty) {
      slivers
        ..add(_groupLabelSliver('手动挑选'))
        ..add(_gridSliver(data, manual));
    }
    for (final reason in unsupported) {
      slivers
        ..add(_groupLabelSliver('相似连拍 · 本期未开启'))
        ..add(_sliverOf(
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text(
              reason,
              style: context.typography.caption.copyWith(
                fontSize: 11.5,
                color: context.colors.ink3,
              ),
            ),
          ),
        ));
    }
    return CustomScrollView(
      slivers: [
        const SliverToBoxAdapter(child: SizedBox(height: 4)),
        ...slivers,
        const SliverToBoxAdapter(child: SizedBox(height: 18)),
      ],
    );
  }

  /// sliver 版网格：外层是唯一滚动体，摆到哪渲染哪（不再 shrinkWrap 全量布局）。
  Widget _sliverOf(Widget child) => SliverPadding(
    padding: const EdgeInsets.symmetric(horizontal: 18),
    sliver: SliverToBoxAdapter(child: child),
  );

  Widget _groupLabelSliver(String text) => _sliverOf(_groupLabel(text));

  Widget _groupLabel(String text) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(2, 16, 2, 9),
      child: Text(
        text,
        style: context.typography.caption.copyWith(
          fontSize: 12,
          fontWeight: FontWeight.w600,
          color: context.colors.ink3,
        ),
      ),
    );
  }

  Widget _gridSliver(AlbumManageData data, List<PhotoAsset> assets) {
    return SliverPadding(
      padding: const EdgeInsets.symmetric(horizontal: 18),
      sliver: SliverGrid.builder(
        gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
          crossAxisCount: PhotoTile.gridCrossAxisCount,
          crossAxisSpacing: PhotoTile.gridSpacing,
          mainAxisSpacing: PhotoTile.gridSpacing,
          childAspectRatio: 1,
        ),
        itemCount: assets.length,
        itemBuilder: (context, index) {
          final asset = assets[index];
          return PhotoTile(
            thumbnail: data.thumbnails[asset.id],
            selectionMode: true,
            selected: _selected.contains(asset.id),
            onToggle: () => _toggle(asset.id),
          );
        },
      ),
    );
  }
}
