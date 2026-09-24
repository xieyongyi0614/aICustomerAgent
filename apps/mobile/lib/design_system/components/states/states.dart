import 'package:flutter/material.dart';

import '../../tokens/tokens.dart';

/// 全站错误文案模板：零技术细节 + 必须给下一步动作。
abstract final class StateCopy {
  static const networkError = '网络好像断了，检查一下再试';
  static const timeout = '等太久了，要不要再试一次';
  static const unauthorized = '需要重新登录一下';
  static const badRequest = '这个操作我没法完成，换个说法试试';
  static const serverError = '我这边有点小问题，稍后再试';
  static const streamInterrupted = '刚才没说完，要我接着说吗';
  static const parseFailure = '我收到了一条看不懂的消息';
  static const retryAction = '再试一次';
  static const emptyDefault = '这里还什么都没有，先去做点什么吧';
}

class LoadingState extends StatelessWidget {
  const LoadingState({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    return Center(
      child: SizedBox(
        width: 28,
        height: 28,
        child: CircularProgressIndicator(
          strokeWidth: 2.4,
          color: colors.aiPrimary,
          backgroundColor: colors.trackBar,
        ),
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    this.message = StateCopy.emptyDefault,
    this.actionLabel,
    this.onAction,
  });

  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, style: type.body.copyWith(color: colors.ink2)),
            if (actionLabel != null) ...[
              const SizedBox(height: 16),
              FilledButton(
                onPressed: onAction,
                child: Text(actionLabel!),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class ErrorState extends StatelessWidget {
  const ErrorState({
    super.key,
    this.message = StateCopy.serverError,
    this.onRetry,
  });

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message, style: type.body.copyWith(color: colors.ink)),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: onRetry,
              child: const Text(StateCopy.retryAction),
            ),
          ],
        ),
      ),
    );
  }
}

/// 骨架屏：与真实内容同尺寸，避免布局跳动。
class Skeleton extends StatelessWidget {
  const Skeleton({
    super.key,
    this.height = 16,
    this.width = double.infinity,
    this.radius = 8,
  });

  final double height;
  final double width;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    return Container(
      height: height,
      width: width,
      decoration: BoxDecoration(
        color: colors.fillSubtle,
        borderRadius: BorderRadius.circular(radius),
      ),
    );
  }
}

class SkeletonCard extends StatelessWidget {
  const SkeletonCard({super.key, this.lines = 2});

  final int lines;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Skeleton(height: 18, width: 120),
          const SizedBox(height: 12),
          for (var i = 0; i < lines; i++) ...[
            Skeleton(height: 14, width: i.isEven ? double.infinity : 180),
            const SizedBox(height: 8),
          ],
        ],
      ),
    );
  }
}

/// AsyncValue 三态 → 四态映射
Widget buildAsyncState<T>({
  required Object? loading,
  required Object? error,
  required T? data,
  required Widget Function(T data) builder,
  Widget? empty,
  VoidCallback? onRetry,
}) {
  if (error != null) {
    return ErrorState(onRetry: onRetry);
  }
  if (loading != null && data == null) {
    return const SkeletonCard();
  }
  if (data == null) {
    return empty ?? const EmptyState();
  }
  return builder(data);
}
