/// PLT-003 客户端埋点：只发脱敏后的安全字段。
library;

import '../network/interceptors/log_redaction_interceptor.dart';

abstract final class Analytics {
  static void Function(String event, Map<String, String> props)? sink;

  static void track(String event, [Map<String, dynamic> props = const {}]) {
    final safe = LogRedactionInterceptor.redactMap({
      'event_type': event,
      ...props,
    });
    sink?.call(event, safe);
  }
}
