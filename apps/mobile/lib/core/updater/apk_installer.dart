import 'package:flutter/services.dart';

import 'release_models.dart';

/// 原生更新通道名。Kotlin 侧 `ApkInstaller.kt` 必须注册同名通道。
const String updatePlatformChannelName = 'com.zhaoxi.app/updater';

/// 平台能力抽象：生产用 `MethodChannelUpdatePlatform`，测试注入假实现。
abstract interface class UpdatePlatform {
  Future<bool> installApk(String apkPath);

  Future<bool> canInstallPackages();

  Future<void> openInstallPermissionSettings();

  Future<int> installedVersionCode();

  /// 运行中 App **自身**的签名指纹（比对锚点，见 APP-044 裁决 D7）。
  Future<String?> installedSignatureFingerprint();

  /// 指定 APK 归档内的签名指纹。
  Future<String?> apkSignatureFingerprint(String apkPath);

  Future<bool> isOnWifi();
}

class MethodChannelUpdatePlatform implements UpdatePlatform {
  const MethodChannelUpdatePlatform();

  static const MethodChannel _channel = MethodChannel(
    updatePlatformChannelName,
  );

  @override
  Future<bool> installApk(String apkPath) async {
    final result = await _channel.invokeMethod<bool>('installApk', {
      'apkPath': apkPath,
    });
    return result ?? false;
  }

  @override
  Future<bool> canInstallPackages() async {
    final result = await _channel.invokeMethod<bool>('canInstallPackages');
    return result ?? false;
  }

  @override
  Future<void> openInstallPermissionSettings() async {
    await _channel.invokeMethod<void>('openInstallPermissionSettings');
  }

  @override
  Future<int> installedVersionCode() async {
    final result = await _channel.invokeMethod<int>('installedVersionCode');
    return result ?? 0;
  }

  @override
  Future<String?> installedSignatureFingerprint() {
    return _channel.invokeMethod<String>('installedSignatureFingerprint');
  }

  @override
  Future<String?> apkSignatureFingerprint(String apkPath) {
    return _channel.invokeMethod<String>('apkSignatureFingerprint', {
      'apkPath': apkPath,
    });
  }

  @override
  Future<bool> isOnWifi() async {
    final result = await _channel.invokeMethod<bool>('isOnWifi');
    return result ?? false;
  }
}

/// 安装通道封装：把平台异常统一成 [UpdateFailureKind.platformError]，
/// **不吞异常、不返回假成功**（静默成功会让状态机与真实世界脱节）。
class ApkInstaller {
  ApkInstaller({UpdatePlatform? platform})
      : _platform = platform ?? const MethodChannelUpdatePlatform();

  final UpdatePlatform _platform;

  Future<bool> canInstallPackages() => _guard(_platform.canInstallPackages);

  Future<int> installedVersionCode() => _guard(_platform.installedVersionCode);

  Future<bool> isOnWifi() => _guard(_platform.isOnWifi);

  Future<String?> installedSignatureFingerprint() =>
      _guard(_platform.installedSignatureFingerprint);

  Future<String?> apkSignatureFingerprint(String apkPath) =>
      _guard(() => _platform.apkSignatureFingerprint(apkPath));

  Future<void> openInstallPermissionSettings() =>
      _guard(_platform.openInstallPermissionSettings);

  /// 调起系统安装器；返回 false 表示未能调起（含未授权场景）。
  Future<bool> installApk(String apkPath) =>
      _guard(() => _platform.installApk(apkPath));

  Future<T> _guard<T>(Future<T> Function() action) async {
    try {
      return await action();
    } on PlatformException catch (error) {
      throw UpdatePlatformException(error.code, error.message);
    } on MissingPluginException catch (error) {
      throw UpdatePlatformException('missingPlugin', error.message);
    }
  }
}

class UpdatePlatformException implements Exception {
  const UpdatePlatformException(this.code, this.message);

  final String code;
  final String? message;

  @override
  String toString() =>
      'UpdatePlatformException($code${message == null ? '' : ': $message'})';
}
