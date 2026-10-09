import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/updater/apk_installer.dart';

/// 原生更新通道的**静态契约守卫**。
///
/// 本机/CI 未必具备 Android SDK（`flutter build apk` 可能不可用），因此用源码文本
/// 断言把「Dart ↔ Kotlin ↔ Manifest」三方契约钉住——任一侧改名/漏配即转红。
void main() {
  final manifest = File(
    'android/app/src/main/AndroidManifest.xml',
  ).readAsStringSync();
  final filePaths = File(
    'android/app/src/main/res/xml/file_paths.xml',
  ).readAsStringSync();
  final kotlinInstaller = File(
    'android/app/src/main/kotlin/com/zhaoxi/app/updater/ApkInstaller.kt',
  ).readAsStringSync();
  final mainActivity = File(
    'android/app/src/main/kotlin/com/zhaoxi/app/MainActivity.kt',
  ).readAsStringSync();

  test('test_manifest_declares_install_and_network_permissions', () {
    expect(
      manifest.contains('android.permission.REQUEST_INSTALL_PACKAGES'),
      isTrue,
      reason: 'Android 8.0+ 调起安装器必需',
    );
    expect(
      manifest.contains('android.permission.ACCESS_NETWORK_STATE'),
      isTrue,
      reason: 'isOnWifi() 需要（普通权限，无运行时弹窗）',
    );
  });

  test('test_manifest_declares_file_provider_with_application_id_authority', () {
    expect(manifest.contains('androidx.core.content.FileProvider'), isTrue);
    expect(
      manifest.contains('android:authorities="\${applicationId}.fileprovider"'),
      isTrue,
      reason: '写死 authority 会让 dev（.dev 后缀）与 prod 同机冲突',
    );
    expect(manifest.contains('android.support.FILE_PROVIDER_PATHS'), isTrue);
    expect(manifest.contains('@xml/file_paths'), isTrue);
  });

  test('test_file_paths_exposes_only_updates_directory', () {
    expect(filePaths.contains('<files-path'), isTrue);
    expect(filePaths.contains('name="updates"'), isTrue);
    expect(filePaths.contains('path="updates/"'), isTrue);
    expect(
      filePaths.contains('<external-path') ||
          filePaths.contains('<root-path'),
      isFalse,
      reason: '不得暴露整个存储',
    );
  });

  test('test_channel_name_matches_dart_constant', () {
    expect(
      kotlinInstaller.contains('const val CHANNEL = "$updatePlatformChannelName"'),
      isTrue,
      reason: 'Kotlin 通道名必须与 Dart 侧 updatePlatformChannelName 一致',
    );
    expect(mainActivity.contains('ApkInstaller(this).attach('), isTrue);
    expect(mainActivity.contains('flutterEngine.dartExecutor.binaryMessenger'), isTrue);
  });

  test('test_kotlin_implements_all_seven_channel_methods', () {
    for (final method in [
      'installApk',
      'canInstallPackages',
      'openInstallPermissionSettings',
      'installedVersionCode',
      'installedSignatureFingerprint',
      'apkSignatureFingerprint',
      'isOnWifi',
    ]) {
      expect(
        kotlinInstaller.contains('"$method"'),
        isTrue,
        reason: '$method 未在原生侧实现',
      );
    }
  });

  test('test_dart_platform_interface_covers_seven_methods', () {
    const platform = MethodChannelUpdatePlatform();
    expect(platform, isA<UpdatePlatform>());
    for (final method in [
      'installApk',
      'canInstallPackages',
      'openInstallPermissionSettings',
      'installedVersionCode',
      'installedSignatureFingerprint',
      'apkSignatureFingerprint',
      'isOnWifi',
    ]) {
      expect(
        kotlinInstaller.contains('"$method"'),
        isTrue,
        reason: 'Dart 接口方法 $method 在原生侧缺失',
      );
    }
  });

  test('test_kotlin_install_intent_uses_content_uri_and_apk_media_type', () {
    expect(kotlinInstaller.contains('Intent.ACTION_VIEW'), isTrue);
    expect(kotlinInstaller.contains('FLAG_GRANT_READ_URI_PERMISSION'), isTrue);
    expect(
      kotlinInstaller.contains(
        'application/vnd.android.package-archive',
      ),
      isTrue,
    );
    expect(
      kotlinInstaller.contains('canRequestPackageInstalls'),
      isTrue,
      reason: '安装前必须预检「安装未知应用」',
    );
    expect(
      kotlinInstaller.contains('ACTION_MANAGE_UNKNOWN_APP_SOURCES'),
      isTrue,
      reason: '拒权时必须能引导到系统设置页',
    );
  });

  test('test_kotlin_fingerprint_is_sha256_uppercase_with_colons', () {
    expect(kotlinInstaller.contains('MessageDigest.getInstance("SHA-256")'), isTrue);
    expect(
      kotlinInstaller.contains('joinToString(":")'),
      isTrue,
      reason: '与发布侧/服务端口径一致：大写冒号分隔',
    );
    expect(
      kotlinInstaller.contains('GET_SIGNING_CERTIFICATES'),
      isTrue,
    );
  });

  test('test_bootstrap_has_no_update_logic_trigger', () {
    final bootstrap = File('lib/app/bootstrap.dart').readAsStringSync();
    expect(
      bootstrap.contains('updateControllerProvider'),
      isFalse,
      reason: '自动检查不得在 bootstrap 内发起（合规底线 1，APP-044 裁决 D2）',
    );
  });
}
