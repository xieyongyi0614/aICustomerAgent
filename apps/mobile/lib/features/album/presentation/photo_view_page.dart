import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';
import 'package:photo_manager/photo_manager.dart';
import 'package:photo_manager_image_provider/photo_manager_image_provider.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';

/// B19 #photoView 单张照片：大图不切深色底，信息行逐项标注「本机读取」。
///
/// 无 AI 结论（无「最清楚 / 连拍」类文案，D16）；删除走系统「最近删除」。
class PhotoViewPage extends StatefulWidget {
  const PhotoViewPage({super.key, this.assetId});

  final String? assetId;

  @override
  State<PhotoViewPage> createState() => _PhotoViewPageState();
}

class _PhotoViewPageState extends State<PhotoViewPage> {
  AssetEntity? _entity;
  bool _loading = true;
  bool _deleting = false;

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
      _loading = false;
    });
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

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final entity = _entity;
    final dateFormat = DateFormat('yyyy 年 M 月 d 日 HH:mm');
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: ListView(
          padding: context.spacing.screenPadding.copyWith(bottom: 40),
          children: [
            BackLink(label: '‹ 相簿', onTap: () => Navigator.of(context).maybePop()),
            const SizedBox(height: 12),
            _bigImage(context),
            const SizedBox(height: 14),
            _infoRow(context, '文件', entity?.title),
            _infoRow(
              context,
              '拍摄时间',
              entity == null ? null : dateFormat.format(entity.createDateTime),
            ),
            _infoRow(context, '来源', entity == null ? null : '本机读取 · 本机归类'),
            const SizedBox(height: 16),
            GestureDetector(
              onTap: _delete,
              child: Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 13),
                decoration: BoxDecoration(
                  color: colors.dangerBg,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  _deleting ? '正在移入「最近删除」…' : '删除',
                  textAlign: TextAlign.center,
                  style: type.caption.copyWith(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w600,
                    color: colors.dangerText,
                  ),
                ),
              ),
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
