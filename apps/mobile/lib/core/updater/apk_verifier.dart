import 'dart:io';

import 'package:crypto/crypto.dart';

import 'apk_installer.dart';
import 'release_models.dart';

/// 流式计算 sha256：不把 20–60 MB 的 APK 整个读进内存。
Future<String> sha256OfFile(File file) async {
  final digest = await sha256.bind(file.openRead()).first;
  return digest.toString();
}

/// 双校验链：体积 → sha256 → **与运行中 App 自身签名比对**。
///
/// 只比服务端清单里的指纹等于没校验（清单与 sha256 同源，被篡改时一起被替换）；
/// 锚定「运行中 App 自己的签名」才是应用身份。
class ApkVerifier {
  const ApkVerifier({required this.installer});

  final ApkInstaller installer;

  /// 返回 null 表示通过，否则返回失败分类。
  Future<UpdateFailureKind?> verify({
    required File file,
    required ReleaseArtifact artifact,
  }) async {
    final length = await file.length();
    if (length != artifact.sizeBytes) {
      return UpdateFailureKind.incomplete;
    }
    final digest = await sha256OfFile(file);
    if (digest.toLowerCase() != artifact.sha256.toLowerCase()) {
      return UpdateFailureKind.hashMismatch;
    }
    final apkFingerprint = await installer.apkSignatureFingerprint(file.path);
    final selfFingerprint = await installer.installedSignatureFingerprint();
    if (apkFingerprint == null || selfFingerprint == null) {
      return UpdateFailureKind.platformError;
    }
    if (normalizeFingerprint(apkFingerprint) !=
        normalizeFingerprint(selfFingerprint)) {
      return UpdateFailureKind.signatureMismatch;
    }
    return null;
  }
}
