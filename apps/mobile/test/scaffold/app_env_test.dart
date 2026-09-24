import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/env/app_env.dart';

void main() {
  test('test_api_base_url_injected_by_dart_define', () {
    expect(
      () => AppEnv.ensureInitialized(),
      throwsA(isA<StateError>()),
      reason: 'must fail closed when API_BASE_URL is missing',
    );
    expect(AppEnv.apiBaseUrl, isEmpty);
  });
}
