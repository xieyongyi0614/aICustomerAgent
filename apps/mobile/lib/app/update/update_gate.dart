import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/updater/update_checker.dart';
import '../../core/updater/update_providers.dart';
import '../theme/theme_context.dart';
import 'update_sheet.dart';

/// 更新域装配层：**首帧之后**触发检查，并托管更新面板。
///
/// 为什么不在 `bootstrap()` 里检查：合规底线要求「未点『同意』前不得发起业务网络请求」，
/// 而同意门控归 `PLT-002`。把触发点放在首帧之后，`PLT-002` 落地后弹窗天然排在它前面，
/// 本类无需改动。
class UpdateGate extends ConsumerStatefulWidget {
  const UpdateGate({super.key, required this.child});

  final Widget child;

  @override
  ConsumerState<UpdateGate> createState() => _UpdateGateState();
}

class _UpdateGateState extends ConsumerState<UpdateGate> {
  bool _startupRequested = false;
  bool _sheetOpen = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || _startupRequested) {
        return;
      }
      _startupRequested = true;
      ref.read(updateControllerProvider.notifier).onStartup();
    });
  }

  bool _sheetWorthy(UpdateState state) {
    if (state.decision == null) {
      return false;
    }
    switch (state.stage) {
      case UpdateStage.available:
      case UpdateStage.confirmWifi:
      case UpdateStage.downloading:
      case UpdateStage.verifying:
      case UpdateStage.readyToInstall:
      case UpdateStage.permissionRequired:
      case UpdateStage.failed:
        return true;
      case UpdateStage.idle:
      case UpdateStage.checking:
      case UpdateStage.upToDate:
        return false;
    }
  }

  Future<void> _openSheet(UpdateState state) async {
    if (_sheetOpen || !mounted) {
      return;
    }
    _sheetOpen = true;
    final force = state.decision?.strategy == UpdateStrategy.force &&
        state.stage == UpdateStage.available;
    try {
      await showModalBottomSheet<void>(
        context: context,
        isScrollControlled: true,
        isDismissible: !force,
        enableDrag: !force,
        backgroundColor: context.colors.surface.withValues(alpha: 0),
        barrierColor: context.colors.ink.withValues(alpha: 0.28),
        builder: (_) => const UpdateSheet(),
      );
    } finally {
      _sheetOpen = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<UpdateState>(updateControllerProvider, (previous, next) {
      if (_sheetWorthy(next)) {
        _openSheet(next);
        return;
      }
      if (_sheetOpen) {
        Navigator.of(context).maybePop();
      }
    });
    return widget.child;
  }
}
