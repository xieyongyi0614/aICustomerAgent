import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/chips.dart';
import '../../../design_system/components/states/states.dart';

/// APP-022 快速捕获：一句话 → 记账/任务（备忘录 kind=memo），可改归。
class CaptureRouteSheet extends StatefulWidget {
  const CaptureRouteSheet({super.key, this.initialText = ''});

  final String initialText;

  @override
  State<CaptureRouteSheet> createState() => _CaptureRouteSheetState();
}

class _CaptureRouteSheetState extends State<CaptureRouteSheet> {
  late final _controller = TextEditingController(text: widget.initialText);
  String? _receipt;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _route(String kind) {
    setState(() {
      _receipt = switch (kind) {
        'ledger' => '已归到「记账」',
        'task' => '已归到「任务」',
        'memo' => '已归到「备忘录」（任务域 memo）',
        _ => '已归位',
      };
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
          if (_receipt == null) ...[
            Row(
              children: [
                ChipButton(label: '记账', onTap: () => _route('ledger')),
                const SizedBox(width: 8),
                ChipButton(label: '任务', onTap: () => _route('task')),
                const SizedBox(width: 8),
                ChipButton(label: '备忘录', onTap: () => _route('memo')),
              ],
            ),
            Text(
              '不确定时先选一个，之后可以一键改归',
              style: type.caption.copyWith(color: colors.ink3),
            ),
          ] else ...[
            MemHintLocal(text: _receipt!),
            const SizedBox(height: 10),
            Row(
              children: [
                ChipButton(label: '改归', ghost: true, onTap: () {
                  setState(() {
                    _receipt = null;
                  });
                }),
                const SizedBox(width: 8),
                ChipButton(label: '完成', onTap: () => Navigator.of(context).pop()),
              ],
            ),
          ],
          const SizedBox(height: 8),
          const Text('非医疗建议，请咨询医生',
              style: TextStyle(fontSize: 11)),
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
