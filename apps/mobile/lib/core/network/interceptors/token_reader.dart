/// 令牌读取接口：实现由 APP-004 注入。
abstract interface class TokenReader {
  Future<String?> readAccessToken();
}

class NoopTokenReader implements TokenReader {
  const NoopTokenReader();

  @override
  Future<String?> readAccessToken() async => null;
}
