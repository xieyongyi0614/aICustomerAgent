import 'package:flutter_riverpod/flutter_riverpod.dart';

/// 登录态纪元：退出登录时 +1。
///
/// 会话内存态（如 chatPageStateProvider）在 build 里 watch 它——纪元一变
/// provider 整体重建，上一账号的消息与流式状态不会串进下一账号；
/// 放在 app/state 让 profile 与 chat 各自依赖它而不互相 import。
final authEpochProvider =
    NotifierProvider<AuthEpochNotifier, int>(AuthEpochNotifier.new);

class AuthEpochNotifier extends Notifier<int> {
  @override
  int build() => 0;

  void bump() => state = state + 1;
}
