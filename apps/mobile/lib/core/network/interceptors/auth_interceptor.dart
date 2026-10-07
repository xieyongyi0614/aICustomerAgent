import 'package:dio/dio.dart';

import 'token_reader.dart';

class AuthInterceptor extends Interceptor {
  AuthInterceptor(this._reader);

  final TokenReader _reader;

  @override
  void onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    try {
      final token = await _reader.readAccessToken();
      if (token != null && token.isNotEmpty) {
        options.headers['Authorization'] = 'Bearer $token';
      }
    } catch (_) {
      // 令牌读取失败不能让请求悬挂在拦截器里：降级匿名发出，
      // 需要鉴权的端点自会以 401 收口。
    }
    handler.next(options);
  }
}
