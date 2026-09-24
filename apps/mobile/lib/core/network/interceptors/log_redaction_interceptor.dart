import 'package:dio/dio.dart';

/// 白名单放行 + 黑名单兜底。
/// 禁打：令牌、金额、健康数值、记忆正文、用户标识、Authorization。
class LogRedactionInterceptor extends Interceptor {
  const LogRedactionInterceptor();

  static const allowedKeys = {
    'method',
    'path',
    'status',
    'duration_ms',
    'event_type',
    'error_kind',
  };

  static const blockedKeys = {
    'authorization',
    'token',
    'access_token',
    'amount',
    'total',
    'balance',
    'price',
    'heart_rate',
    'steps',
    'sleep',
    'weight',
    'systolic',
    'diastolic',
    'spo2',
    'memory',
    'user_id',
    'uid',
    'body',
    'content',
    'message',
    'delta',
    'detail',
    'error',
  };

  static String redact(String key, String value) {
    final lower = key.toLowerCase();
    if (blockedKeys.contains(lower) || lower.contains('amount')) {
      return '[redacted]';
    }
    return value;
  }

  static Map<String, String> redactMap(Map<String, dynamic> raw) {
    final out = <String, String>{};
    for (final e in raw.entries) {
      final k = e.key.toLowerCase();
      if (!allowedKeys.contains(k) && blockedKeys.contains(k)) {
        out[e.key] = '[redacted]';
      } else if (blockedKeys.contains(k)) {
        out[e.key] = '[redacted]';
      } else {
        out[e.key] = '${e.value}';
      }
    }
    return out;
  }

  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    // 只记录白名单安全字段
    // ignore: avoid_print
    print('[net] req ${options.method} ${options.uri.path}');
    handler.next(options);
  }

  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    // ignore: avoid_print
    print('[net] res ${response.statusCode} ${response.requestOptions.uri.path}');
    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final kind = err.error is Object ? err.error.runtimeType.toString() : 'unknown';
    // ignore: avoid_print
    print('[net] err ${err.type.name} $kind');
    handler.next(err);
  }
}
