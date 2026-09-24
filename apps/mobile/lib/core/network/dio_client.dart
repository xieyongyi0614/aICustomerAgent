import 'package:dio/dio.dart';

import '../env/app_env.dart';
import 'interceptors/auth_interceptor.dart';
import 'interceptors/error_mapping_interceptor.dart';
import 'interceptors/log_redaction_interceptor.dart';
import 'interceptors/token_reader.dart';

Dio createDio({
  TokenReader tokenReader = const NoopTokenReader(),
  String? baseUrl,
}) {
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
    const ErrorMappingInterceptor(),
    const LogRedactionInterceptor(),
  ]);
  return dio;
}

/// 流式请求：接收超时按首 token 预算单独设置
const streamFirstTokenTimeout = Duration(milliseconds: 1500);
const streamIdleTimeout = Duration(milliseconds: 60000);
