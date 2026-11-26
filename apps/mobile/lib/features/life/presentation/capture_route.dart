import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/chips.dart';
import '../../../design_system/components/states/states.dart';
import '../data/life_repository.dart';

enum CaptureRouteKind { ledger, task, memo }

class CaptureRouteResult {
  const CaptureRouteResult({required this.receipt, this.taskId});

  final String receipt;

  /// 非空 = 已落任务域，可改归（删除后重选）。
  final String? taskId;
}

typedef CaptureRouter = Future<CaptureRouteResult> Function(
  CaptureRouteKind kind,
  String text,
);

Future<CaptureRouteResult> routeToTaskDomain(
  LifeRepository repo,
  CaptureRouteKind kind,
  String text,
) async {
  final kindStr = kind == CaptureRouteKind.task ? 'task' : 'memo';
  final task = await repo.createTask(title: text, kind: kindStr);
  final label = kind == CaptureRouteKind.task ? '任务' : '备忘录';
  return CaptureRouteResult(receipt: '已归到「$label」', taskId: task.id);
}

/// APP-022 快速捕获（V1 降级裁决：无 AI 意图分类，用户显式归位）：
/// 任务/备忘录真落任务域（kind=memo）；记账经对话链路（预填文本跳转聊天）。
class CaptureRouteSheet extends StatefulWidget {
  const CaptureRouteSheet({
    super.key,
    this.initialText = '',
    this.debugRouter,
    this.debugReclassify,
  });

  final String initialText;

  /// 测试注入；生产走 routeToTaskDomain。
  final CaptureRouter? debugRouter;

  /// 测试注入；生产走 LifeRepository.deleteTask。
  final Future<void> Function(String taskId)? debugReclassify;

  @override
  State<CaptureRouteSheet> createState() => _CaptureRouteSheetState();
}

class _CaptureRouteSheetState extends State<CaptureRouteSheet> {
  late final _controller = TextEditingController(text: widget.initialText);
  final _repo = LifeRepository();
  String? _receipt;
  String? _createdTaskId;
  bool _busy = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  CaptureRouter get _router =>
      widget.debugRouter ?? (kind, text) => routeToTaskDomain(_repo, kind, text);

  Future<void> _route(CaptureRouteKind kind) async {
    if (_busy) return;
    final text = _controller.text.trim();
    if (text.isEmpty) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(const SnackBar(content: Text('先写一句话，再选归到哪里')));
      return;
    }
    if (kind == CaptureRouteKind.ledger) {
      final router = GoRouter.of(context);
      Navigator.of(context).pop();
      router.go('/chat', extra: text);
      return;
    }
    setState(() => _busy = true);
    try {
      final result = await _router(kind, text);
      if (!mounted) return;
      setState(() {
        _receipt = result.receipt;
        _createdTaskId = result.taskId;
      });
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(const SnackBar(content: Text('归位失败，请检查网络后重试')));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _reclassify() async {
    final taskId = _createdTaskId;
    if (taskId != null) {
      setState(() => _busy = true);
      try {
        await (widget.debugReclassify ?? _repo.deleteTask)(taskId);
      } catch (_) {
        if (!mounted) return;
        ScaffoldMessenger.of(context)
          ..hideCurrentSnackBar()
          ..showSnackBar(const SnackBar(content: Text('撤回落位失败，可稍后在任务里处理')));
        return;
      } finally {
        if (mounted) setState(() => _busy = false);
      }
    }
    if (!mounted) return;
    setState(() {
      _receipt = null;
      _createdTaskId = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Padding(
      padding: EdgeInsets.only(
        left: 18,
        right: 18,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('快速捕获', style: type.sectionTitle),
          const SizedBox(height: 10),
          TextField(
            controller: _controller,
            decoration: const InputDecoration(
              hintText: '「记一下，下个月准备去旅行」…',
            ),
          ),
          const SizedBox(height: 14),
          if (_busy)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 10),
              child: SizedBox(
                width: 20,
                height: 20,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            )
          else if (_receipt == null) ...[
            Row(
              children: [
                ChipButton(
                  label: '记账',
                  onTap: () => _route(CaptureRouteKind.ledger),
                ),
                const SizedBox(width: 8),
                ChipButton(
                  label: '任务',
                  onTap: () => _route(CaptureRouteKind.task),
                ),
                const SizedBox(width: 8),
                ChipButton(
                  label: '备忘录',
                  onTap: () => _route(CaptureRouteKind.memo),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              '「记账」会把这句话交给亚丝娜在对话里入账；任务与备忘录直接落位，之后可一键改归',
              style: type.caption.copyWith(color: colors.ink3, height: 1.5),
            ),
          ] else ...[
            MemHintLocal(text: _receipt!),
            const SizedBox(height: 10),
            Row(
              children: [
                ChipButton(label: '改归', ghost: true, onTap: _reclassify),
                const SizedBox(width: 8),
                ChipButton(
                  label: '完成',
                  onTap: () => Navigator.of(context).pop(),
                ),
              ],
            ),
          ],
          const SizedBox(height: 8),
          Text(
            '非医疗建议，请咨询医生',
            style: type.caption.copyWith(color: colors.ink3),
          ),
        ],
      ),
    );
  }
}

class MemHintLocal extends StatelessWidget {
  const MemHintLocal({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    return MemHint(text: text);
  }
}

/// 低置信澄清空态
class CaptureClarify extends StatelessWidget {
  const CaptureClarify({super.key, required this.onPick});

  final void Function(String kind) onPick;

  @override
  Widget build(BuildContext context) {
    return EmptyState(
      message: '我没太确定要放到哪里，你选一下？',
      actionLabel: '记账',
      onAction: () => onPick('ledger'),
    );
  }
}
