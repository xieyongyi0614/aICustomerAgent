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
    final token = await _reader.readAccessToken();
    if (token != null && token.isNotEmpty) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }
}
