/// 配置经 --dart-define 注入；未注入时启动即失败，不得静默回退硬编码地址。
abstract final class AppEnv {
  static const String apiBaseUrl = String.fromEnvironment('API_BASE_URL');
  static const String flavor = String.fromEnvironment('APP_FLAVOR', defaultValue: 'dev');

  static void ensureInitialized() {
    if (apiBaseUrl.isEmpty) {
      throw StateError(
        'API_BASE_URL is required. '
        'Run with --dart-define=API_BASE_URL=<url> --dart-define=APP_FLAVOR=<dev|prod>.',
      );
    }
  }
}
