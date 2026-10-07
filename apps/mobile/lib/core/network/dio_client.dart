import 'package:dio/dio.dart';

import '../env/app_env.dart';
import '../storage/secure_token_store.dart';
import 'interceptors/auth_interceptor.dart';
import 'interceptors/error_mapping_interceptor.dart';
import 'interceptors/log_redaction_interceptor.dart';
import 'interceptors/token_reader.dart';
import 'session_expiry.dart';

Dio? _sharedDio;
TokenReader? _sharedTokenReader;

/// 全进程共享一个 Dio 实例：此前每个页面各自 createDio，各建一套连接池、
/// 各读一次 Keystore（审计实测 14 处调用 13 个文件）。传 baseUrl /
/// tokenReader 的定制调用方（测试、特殊端点）不参与共享。
Dio createDio({TokenReader? tokenReader, String? baseUrl}) {
  if (tokenReader == null && baseUrl == null) {
    _sharedTokenReader ??= SecureTokenStore();
    return _sharedDio ??= _build(tokenReader: _sharedTokenReader!);
  }
  return _build(
    tokenReader: tokenReader ?? SecureTokenStore(),
    baseUrl: baseUrl,
  );
}

Dio _build({required TokenReader tokenReader, String? baseUrl}) {
  final dio = Dio(
    BaseOptions(
      baseUrl: baseUrl ?? AppEnv.apiBaseUrl,
      connectTimeout: const Duration(milliseconds: 10000),
      receiveTimeout: const Duration(milliseconds: 15000),
      responseType: ResponseType.json,
    ),
  );
  dio.interceptors.addAll([
    AuthInterceptor(tokenReader),
    const UnauthorizedGuard(),
    const ErrorMappingInterceptor(),
    const LogRedactionInterceptor(),
  ]);
  return dio;
}

/// 令牌失效统一收口（见 session_expiry.dart）：无论后续错误如何被映射，
/// 401 都要先触发一次「会话过期」动作。
class UnauthorizedGuard extends Interceptor {
  const UnauthorizedGuard();

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    if (err.response?.statusCode == 401) {
      notifyUnauthorized();
    }
    handler.next(err);
  }
}

/// 流式请求：接收超时按首 token 预算单独设置
const streamFirstTokenTimeout = Duration(milliseconds: 1500);
const streamIdleTimeout = Duration(milliseconds: 60000);
