import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import 'album_manage_page.dart';
import '../data/album_analysis.dart';
import '../data/album_repository.dart';
import '../domain/album_models.dart';

/// B18 #albumDetail 相簿详情：按拍摄日期分组、视频带时长徽章。
///
/// AI 整理卡只在本相簿真实分析出可清理项时出现（过期截图 / 重复保存）；
/// 相似连拍本期未开启（D16）→ 页内无 ✦ 连拍徽章、不编造「最清楚的一张」。
class AlbumDetailPage extends StatefulWidget {
  const AlbumDetailPage({
    super.key,
    this.repository,
    this.analyzer,
    this.albumId,
    this.albumName,
    this.preloaded,
  });

  final AlbumRepository? repository;
  final AlbumAnalyzer? analyzer;
  final String? albumId;
  final String? albumName;

  final AlbumManageData? preloaded;

  @override
  State<AlbumDetailPage> createState() => _AlbumDetailPageState();
}

class _AlbumDetailPageState extends State<AlbumDetailPage> {
  late final AlbumRepository _repo = widget.repository ?? AlbumRepository();
  late final AlbumAnalyzer _analyzer =
      widget.analyzer ?? const AlbumAnalyzer();
  bool _loading = true;
  List<PhotoAsset> _assets = [];
  Map<String, ImageProvider?> _thumbs = {};
  AlbumAnalysisResult? _analysis;

  @override
  void initState() {
    super.initState();
    _begin();
  }

  Future<void> _begin() async {
    setState(() {
      _loading = true;
      _analysis = null;
    });
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
    unawaited(_analyze());
  }

  /// 本相簿的整理分析：只读、不阻塞照片墙呈现。
  Future<void> _analyze() async {
    final albumId = widget.albumId;
    if (albumId == null) return;
    try {
      final snapshots = await _repo.scanSnapshots(bucketId: albumId);
      if (!mounted || snapshots == null) return;
      final result = await _analyzer.analyze(snapshots);
      if (!mounted) return;
      setState(() => _analysis = result);
    } catch (_) {
      if (!mounted) return;
      setState(() => _analysis = null);
    }
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
            if (_cleanableCount > 0) ...[
              const SizedBox(height: 14),
              AiCard(
                title: '亚丝娜的整理建议',
                actionLabel: '去看这 $_cleanableCount 张，已帮你预选 →',
                onAction: _pushManage,
                child: Text(
                  '$_cleanableHintText，腾出 $_cleanableSizeText',
                  style: type.body.copyWith(
                    color: colors.bodyOnCard,
                    height: 1.65,
                  ),
                ),
              ),
            ],
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
                    _dayHint(entry.value),
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
                    onTap: () async {
                      await context.push(
                          '/album/photo?id=${Uri.encodeComponent(asset.id)}');
                      if (!mounted) return;
                      await _begin();
                    },
                  );
                },
              ),
            ],
            const SizedBox(height: 16),
            ChipButton(label: '批量管理这个相簿', ghost: true, onTap: _pushManage),
            PrivacyNote(
              child: Text(
                '归类 / 清理建议都在本机算，相册功能无需联网即可使用，不上传服务器；'
                '删除进系统「最近删除」保留 30 天',
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _pushManage() async {
    final albumId = widget.albumId;
    final name = widget.albumName;
    final query = [
      if (albumId != null) 'album=${Uri.encodeComponent(albumId)}',
      if (name != null) 'name=${Uri.encodeComponent(name)}',
    ].join('&');
    await context.push(query.isEmpty ? '/album/manage' : '/album/manage?$query');
    if (!mounted) return;
    await _begin();
  }

  int get _cleanableCount {
    final analysis = _analysis;
    if (analysis == null) return 0;
    return analysis.sections.fold<int>(
      0,
      (sum, section) =>
          section.supported && section.suggestion != null
              ? sum + section.suggestion!.count
              : sum,
    );
  }

  int get _cleanableBytes {
    final analysis = _analysis;
    if (analysis == null) return 0;
    return analysis.sections.fold<int>(
      0,
      (sum, section) =>
          section.supported && section.suggestion != null
              ? sum + section.suggestion!.totalBytes
              : sum,
    );
  }

  String get _cleanableHintText {
    final analysis = _analysis;
    if (analysis == null) return '';
    final parts = <String>[];
    for (final section in analysis.sections) {
      final suggestion = section.suggestion;
      if (!section.supported || suggestion == null) continue;
      if (suggestion.count == 0) continue;
      parts.add(
        '${suggestion.count} 张'
        '${section.kind == AlbumSuggestionKind.expiredScreenshots ? '过期截图' : '重复保存'}',
      );
    }
    return '${parts.join(' + ')}可清理';
  }

  String get _cleanableSizeText {
    final bytes = _cleanableBytes;
    if (bytes >= 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} GB';
    }
    return '${(bytes / 1024).round()} MB';
  }

  String _dayHint(List<PhotoAsset> assets) {
    final videos = assets.where((asset) => asset.isVideo).length;
    return videos == 0 ? '${assets.length} 张' : '${assets.length} 张 · $videos 段视频';
  }

  String _format(Duration d) {
    final minutes = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final seconds = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }
}
