import 'package:flutter_riverpod/flutter_riverpod.dart';

/// 相册摘要全局态：相册域（仅本机数据）写入，生活页相册卡只读。
///
/// 这是一条既非跨域 import（layer_guards 禁止 features/life import
/// features/album）又非后端端点的通道——相册张数是纯端侧数据。
class AlbumSummary {
  const AlbumSummary({
    required this.authorized,
    required this.totalCount,
  });

  final bool authorized;

  /// 本机照片张数；未授权或尚未扫描时为 null（诚实缺省，不显示数字）。
  final int? totalCount;
}

final albumSummaryProvider =
    NotifierProvider<AlbumSummaryNotifier, AlbumSummary?>(
  AlbumSummaryNotifier.new,
);

class AlbumSummaryNotifier extends Notifier<AlbumSummary?> {
  @override
  AlbumSummary? build() => null;

  void update(AlbumSummary summary) => state = summary;
}
