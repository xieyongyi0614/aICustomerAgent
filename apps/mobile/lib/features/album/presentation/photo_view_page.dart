import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:photo_manager/photo_manager.dart';
import 'package:photo_manager_image_provider/photo_manager_image_provider.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/album_repository.dart';
import '../domain/album_models.dart';
import 'album_move_sheet.dart';

/// B19 #photoView 单张照片：大图不切深色底，「照片信息」逐项标注本机口径。
///
/// 无 AI 结论（无「最清楚 / 连拍 / 我留了这张」类文案，D16）；
/// 删除走系统「最近删除」，收藏与移动用系统能力、平台不支持时呈诚实失败态。
class PhotoViewPage extends StatefulWidget {
  const PhotoViewPage({super.key, this.assetId});

  final String? assetId;

  @override
  State<PhotoViewPage> createState() => _PhotoViewPageState();
}

class _PhotoViewPageState extends State<PhotoViewPage> {
  final AlbumRepository _repo = AlbumRepository();
  AssetEntity? _entity;
  bool _loading = true;
  bool _deleting = false;
  bool? _favorite;

  @override
  void initState() {
    super.initState();
    _begin();
  }

  Future<void> _begin() async {
    final id = widget.assetId;
    if (id == null) {
      setState(() => _loading = false);
      return;
    }
    final entity = await AssetEntity.fromId(id);
    if (!mounted) return;
    setState(() {
      _entity = entity;
      _favorite = entity?.isFavorite;
      _loading = false;
    });
  }

  Future<void> _toggleFavorite() async {
    final entity = _entity;
    final current = _favorite;
    if (entity == null || current == null) return;
    final next = !current;
    final ok = await _repo.setFavorite(
      _toPhotoAsset(entity),
      favorite: next,
    );
    if (!mounted) return;
    if (ok) {
      setState(() => _favorite = next);
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('这台设备不支持写入收藏状态')),
      );
    }
  }

  Future<void> _moveToAlbum() async {
    final entity = _entity;
    if (entity == null) return;
    final target = await showAlbumMovePicker(context, _repo);
    if (target == null || !mounted) return;
    final ok = await _repo.moveToAlbum(_toPhotoAsset(entity), target);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          ok ? '已移动到「${target.name}」' : '这张设备不支持移动',
        ),
      ),
    );
  }

  Future<void> _delete() async {
    final entity = _entity;
    if (entity == null || _deleting) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        content: const Text('删除这张照片？删除后进系统「最近删除」，30 天内可恢复。'),
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
    setState(() => _deleting = true);
    await PhotoManager.editor.deleteWithIds([entity.id]);
    if (!mounted) return;
    context.pop();
  }

  PhotoAsset _toPhotoAsset(AssetEntity entity) => PhotoAsset(
        id: entity.id,
        title: entity.title ?? entity.id,
        bucketId: '',
        takenAt: entity.createDateTime,
        sizeBytes: 0,
        isVideo: entity.type == AssetType.video,
        duration: null,
        isScreenshot: false,
      );

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final entity = _entity;
    final dateFormat = DateFormat('yyyy 年 M 月 d 日 HH:mm');
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: context.spacing.screenPadding.copyWith(bottom: 24),
                children: [
                  BackLink(label: '相簿'),
                  const SizedBox(height: 12),
                  _bigImage(context),
                  const SizedBox(height: 18),
                  Row(
                    children: [
                      Text('照片信息', style: type.sectionTitle.copyWith(fontSize: 15)),
                      const Spacer(),
                      Text(
                        '本机读取',
                        style: type.caption.copyWith(
                          fontSize: 11.5,
                          color: colors.ink3,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 4),
                  _infoRow(
                    context,
                    '拍摄时间',
                    entity == null ? null : dateFormat.format(entity.createDateTime),
                  ),
                  _infoRow(
                    context,
                    '尺寸',
                    entity == null || entity.width == 0 || entity.height == 0
                        ? null
                        : '${entity.width} × ${entity.height}',
                  ),
                  _infoRow(context, '来源', entity == null ? null : '本机读取 · 本机归类'),
                ],
              ),
            ),
            AlbumActionBar(
              actions: [
                AlbumAction(
                  label: _favorite == true ? '已收藏' : '收藏',
                  icon: AppIcons.heart,
                  onTap: _toggleFavorite,
                ),
                AlbumAction(
                  label: '移到相簿',
                  icon: AppIcons.move,
                  onTap: _moveToAlbum,
                ),
                AlbumAction(
                  label: _deleting ? '正在移入…' : '删除',
                  icon: AppIcons.trash,
                  danger: true,
                  onTap: _deleting ? null : _delete,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _bigImage(BuildContext context) {
    final colors = context.colors;
    final entity = _entity;
    if (_loading) return const SkeletonCard();
    if (entity == null) {
      return Text(
        '这张照片可能已被删除',
        style: context.typography.body.copyWith(color: colors.ink2),
      );
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxHeight: 480),
        child: Image(
          image: AssetEntityImageProvider(entity, isOriginal: true),
          fit: BoxFit.contain,
          alignment: Alignment.topCenter,
        ),
      ),
    );
  }

  Widget _infoRow(BuildContext context, String label, String? value) {
    final colors = context.colors;
    final type = context.typography;
    if (value == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          SizedBox(
            width: 64,
            child: Text(
              label,
              style: type.caption.copyWith(fontSize: 12.5, color: colors.ink3),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: type.body.copyWith(
                fontWeight: FontWeight.w600,
                fontFeatures: AppTypography.tabular,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
