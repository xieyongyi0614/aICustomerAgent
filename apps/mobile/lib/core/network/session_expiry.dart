import 'dart:async';

/// 令牌失效（401）的统一出口：bootstrap 注册具体动作
/// （清凭据、重建会话内存态、跳登录页），网络层只负责发现与触发。
///
/// 此前 ErrorMappingInterceptor 把 401 映射成 AppError.unauthorized 后
/// 无人消费，令牌过期时用户卡在反复失败。
void Function()? onUnauthorized;

void notifyUnauthorized() {
  final callback = onUnauthorized;
  if (callback == null) return;
  unawaited(Future.sync(callback));
}
