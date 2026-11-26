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
    final safe = redactMap({
      'method': options.method,
      'path': options.uri.path,
    });
    // ignore: avoid_print
    print('[net] req $safe');
    handler.next(options);
  }

  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    final safe = redactMap({
      'method': response.requestOptions.method,
      'path': response.requestOptions.uri.path,
      'status': response.statusCode,
      'duration_ms': response.requestOptions.extra['duration_ms'],
    });
    // ignore: avoid_print
    print('[net] res $safe');
    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final kind = err.error is Object ? err.error.runtimeType.toString() : 'unknown';
    final safe = redactMap({
      'path': err.requestOptions.uri.path,
      'error_kind': '${err.type.name}/$kind',
    });
    // ignore: avoid_print
    print('[net] err $safe');
    handler.next(err);
  }
}
