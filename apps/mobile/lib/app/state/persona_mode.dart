import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design_system/components/mode_selector.dart';

/// 人格相处模式全局态：对话页状态栏 / 模式面板与我的页人格卡共用一份。
final personaModeProvider =
    NotifierProvider<PersonaModeNotifier, RoleMode>(PersonaModeNotifier.new);

class PersonaModeNotifier extends Notifier<RoleMode> {
  @override
  RoleMode build() => RoleMode.defaultMode;

  void set(RoleMode mode) => state = mode;
}
