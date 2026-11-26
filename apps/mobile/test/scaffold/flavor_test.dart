import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('test_both_flavors_configured', () {
    final gradle = File('android/app/build.gradle.kts').readAsStringSync();
    expect(gradle.contains('create("dev")'), isTrue);
    expect(gradle.contains('create("prod")'), isTrue);
    expect(gradle.contains('applicationIdSuffix = ".dev"'), isTrue);
  });

  test('test_api_base_url_injected_by_dart_define', () {
    final env = File('lib/core/env/app_env.dart').readAsStringSync();
    expect(env.contains("String.fromEnvironment('API_BASE_URL')"), isTrue);
    expect(env.contains('StateError'), isTrue);
  });
}
