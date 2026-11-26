import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:path_provider/path_provider.dart';

import '../env/app_env.dart';
import '../storage/prefs_store.dart';
import 'apk_downloader.dart';
import 'apk_installer.dart';
import 'apk_verifier.dart';
import 'release_api.dart';
import 'release_models.dart';
import 'update_checker.dart';

/// 自动检查节流窗口：手动检查不受它限制。
const Duration autoCheckInterval = Duration(hours: 24);

enum UpdateStage {
  idle,
  checking,
  upToDate,
  available,
  confirmWifi,
  downloading,
  verifying,
  readyToInstall,
  permissionRequired,
  failed,
}

class LocalVersion {
  const LocalVersion({required this.versionCode, required this.versionName});

  final int versionCode;
  final String versionName;
}

class UpdateState {
  const UpdateState({
    this.stage = UpdateStage.idle,
    this.decision,
    this.localVersion,
    this.receivedBytes = 0,
    this.totalBytes = 0,
    this.failure,
    this.checkedAt,
    this.wifiOnly = true,
    this.installSupported = true,
  });

  final UpdateStage stage;
  final UpdateDecision? decision;
  final LocalVersion? localVersion;
  final int receivedBytes;
  final int totalBytes;
  final UpdateFailureKind? failure;
  final DateTime? checkedAt;
  final bool wifiOnly;
  final bool installSupported;

  bool get busy =>
      stage == UpdateStage.checking ||
      stage == UpdateStage.downloading ||
      stage == UpdateStage.verifying;

  double? get progress {
    if (totalBytes <= 0) {
      return null;
    }
    return (receivedBytes / totalBytes).clamp(0, 1).toDouble();
  }

  String get versionLabel => localVersion == null
      ? ''
      : 'v${localVersion!.versionName}';

  UpdateState copyWith({
    UpdateStage? stage,
    UpdateDecision? decision,
    LocalVersion? localVersion,
    int? receivedBytes,
    int? totalBytes,
    UpdateFailureKind? failure,
    DateTime? checkedAt,
    bool? wifiOnly,
    bool? installSupported,
    bool clearFailure = false,
    bool clearDecision = false,
  }) {
    return UpdateState(
      stage: stage ?? this.stage,
      decision: clearDecision ? null : (decision ?? this.decision),
      localVersion: localVersion ?? this.localVersion,
      receivedBytes: receivedBytes ?? this.receivedBytes,
      totalBytes: totalBytes ?? this.totalBytes,
      failure: clearFailure ? null : (failure ?? this.failure),
      checkedAt: checkedAt ?? this.checkedAt,
      wifiOnly: wifiOnly ?? this.wifiOnly,
      installSupported: installSupported ?? this.installSupported,
    );
  }
}

class UpdateDependencies {
  const UpdateDependencies({
    required this.api,
    required this.downloader,
    required this.verifier,
    required this.installer,
    required this.loadLocalVersion,
    required this.loadUpdatesDirectory,
    this.installSupported,
  });

  final ReleaseApi api;
  final ApkDownloader downloader;
  final ApkVerifier verifier;
  final ApkInstaller installer;
  final Future<LocalVersion> Function() loadLocalVersion;
  final Future<Directory> Function() loadUpdatesDirectory;
  final bool? installSupported;

  bool get installsEnabled => installSupported ?? AppEnv.flavor == 'prod';
}

Future<LocalVersion> defaultLocalVersionLoader() async {
  final info = await PackageInfo.fromPlatform();
  return LocalVersion(
    versionCode: int.tryParse(info.buildNumber) ?? 0,
    versionName: info.version,
  );
}

Future<Directory> defaultUpdatesDirectoryLoader() async {
  final base = await getApplicationSupportDirectory();
  return Directory('${base.path}${Platform.pathSeparator}updates');
}

final updateDependenciesProvider = Provider<UpdateDependencies>((ref) {
  final installer = ApkInstaller();
  final api = ReleaseApi();
  return UpdateDependencies(
    api: api,
    downloader: ApkDownloader(api: api),
    verifier: ApkVerifier(installer: installer),
    installer: installer,
    loadLocalVersion: defaultLocalVersionLoader,
    loadUpdatesDirectory: defaultUpdatesDirectoryLoader,
  );
});

final updateControllerProvider =
    NotifierProvider<UpdateController, UpdateState>(UpdateController.new);

class UpdateController extends Notifier<UpdateState> {
  CancelToken? _cancelToken;

  UpdateDependencies get _deps => ref.read(updateDependenciesProvider);

  @override
  UpdateState build() => UpdateState(installSupported: true);

  /// 启动挂点：**不在 `bootstrap()` 内**，由首帧后的装配层调用（合规底线：
  /// 未点「同意」前不得发起业务网络请求，而同意门控归 `PLT-002`）。
  Future<void> onStartup() async {
    final deps = _deps;
    final prefs = await PrefsStore.load();
    state = state.copyWith(
      installSupported: deps.installsEnabled,
      wifiOnly: prefs.updateWifiOnly(),
    );
    try {
      state = state.copyWith(localVersion: await deps.loadLocalVersion());
    } on Object {
      state = state.copyWith(localVersion: null);
    }
    await _recoverAfterUpgrade(prefs);
    await _cleanResidualFiles();
    if (!_shouldAutoCheck(prefs)) {
      return;
    }
    await check(manual: false);
  }

  Future<void> check({required bool manual}) async {
    final deps = _deps;
    final prefs = await PrefsStore.load();
    final local = state.localVersion ?? await _safeLocalVersion(deps);
    state = state.copyWith(
      stage: UpdateStage.checking,
      clearFailure: true,
      localVersion: local,
      wifiOnly: prefs.updateWifiOnly(),
      installSupported: deps.installsEnabled,
    );
    try {
      final result = await deps.api.fetchLatest(
        platform: 'android',
        channel: AppEnv.flavor == 'prod' ? 'prod' : 'dev',
        versionCode: local?.versionCode ?? 0,
      );
      final decision = decideUpdate(
        result: result,
        localVersionCode: local?.versionCode ?? 0,
        ignoredVersionCode: prefs.ignoredUpdateVersionCode(),
      );
      final now = DateTime.now();
      await prefs.setUpdateLastCheckAtMillis(now.millisecondsSinceEpoch);
      if (!decision.installable) {
        state = state.copyWith(
          stage: UpdateStage.upToDate,
          decision: decision,
          checkedAt: now,
          clearFailure: decision.failure == null,
          failure: decision.failure,
        );
        return;
      }
      state = state.copyWith(
        stage: UpdateStage.available,
        decision: decision,
        checkedAt: now,
        clearFailure: true,
        receivedBytes: 0,
        totalBytes: decision.artifact!.sizeBytes,
      );
    } on UpdateApiException catch (error) {
      state = state.copyWith(
        stage: UpdateStage.failed,
        failure: error.kind,
      );
    }
  }

  /// `dev` flavor 只检测不安装：防开发机被线上包覆盖、防打断联调。
  Future<void> startDownload() async {
    final decision = state.decision;
    if (decision == null || decision.artifact == null) {
      return;
    }
    if (!state.installSupported) {
      return;
    }
    if (state.wifiOnly && !await _safeIsOnWifi()) {
      state = state.copyWith(stage: UpdateStage.confirmWifi);
      return;
    }
    await _download(decision.artifact!);
  }

  Future<void> confirmWifiAndDownload() async {
    final artifact = state.decision?.artifact;
    if (artifact == null) {
      return;
    }
    await _download(artifact);
  }

  Future<void> retry() async {
    final artifact = state.decision?.artifact;
    if (artifact == null) {
      return;
    }
    await _download(artifact);
  }

  void cancelDownload() {
    _cancelToken?.cancel('user-cancelled');
    _cancelToken = null;
  }

  Future<void> ignoreCurrentVersion() async {
    final latest = state.decision?.latest;
    if (latest == null) {
      return;
    }
    final prefs = await PrefsStore.load();
    await prefs.setIgnoredUpdateVersionCode(latest.versionCode);
    await _cleanResidualFiles();
    state = const UpdateState();
  }

  Future<void> setWifiOnly(bool value) async {
    final prefs = await PrefsStore.load();
    await prefs.setUpdateWifiOnly(value);
    state = state.copyWith(wifiOnly: value);
  }

  Future<void> openInstallPermissionSettings() async {
    try {
      await _deps.installer.openInstallPermissionSettings();
    } on UpdatePlatformException {
      state = state.copyWith(
        stage: UpdateStage.failed,
        failure: UpdateFailureKind.platformError,
      );
    }
  }

  Future<void> install() async {
    final readyFile = state.decision == null ? null : await _targetFile();
    if (readyFile == null || !readyFile.existsSync()) {
      await retry();
      return;
    }
    var allowed = false;
    try {
      allowed = await _deps.installer.canInstallPackages();
    } on UpdatePlatformException {
      state = state.copyWith(
        stage: UpdateStage.failed,
        failure: UpdateFailureKind.platformError,
      );
      return;
    }
    if (!allowed) {
      state = state.copyWith(stage: UpdateStage.permissionRequired);
      return;
    }
    try {
      final launched = await _deps.installer.installApk(readyFile.path);
      if (!launched) {
        state = state.copyWith(
          stage: UpdateStage.failed,
          failure: UpdateFailureKind.platformError,
        );
        return;
      }
      state = state.copyWith(stage: UpdateStage.readyToInstall);
    } on UpdatePlatformException {
      state = state.copyWith(
        stage: UpdateStage.failed,
        failure: UpdateFailureKind.platformError,
      );
    }
  }

  void dismiss() {
    state = const UpdateState();
  }

  Future<void> _download(ReleaseArtifact artifact) async {
    final deps = _deps;
    final target = await _targetFile();
    if (target == null) {
      state = state.copyWith(
        stage: UpdateStage.failed,
        failure: UpdateFailureKind.platformError,
      );
      return;
    }
    _cancelToken = CancelToken();
    state = state.copyWith(
      stage: UpdateStage.downloading,
      clearFailure: true,
      receivedBytes: 0,
      totalBytes: artifact.sizeBytes,
    );
    final outcome = await deps.downloader.download(
      artifact: artifact,
      target: target,
      cancelToken: _cancelToken,
      onProgress: (received, total) {
        if (state.stage == UpdateStage.downloading) {
          state = state.copyWith(receivedBytes: received, totalBytes: total);
        }
      },
    );
    _cancelToken = null;
    if (!outcome.ok) {
      if (outcome.failure == UpdateFailureKind.hashMismatch) {
        await _deleteQuietly(target);
      }
      state = state.copyWith(
        stage: UpdateStage.failed,
        failure: outcome.failure,
        receivedBytes: outcome.receivedBytes,
      );
      return;
    }
    state = state.copyWith(stage: UpdateStage.verifying);
    UpdateFailureKind? failure;
    try {
      failure = await deps.verifier.verify(file: target, artifact: artifact);
    } on UpdatePlatformException catch (error) {
      debugPrint('签名通道异常：$error');
      failure = UpdateFailureKind.platformError;
    }
    if (failure != null) {
      debugPrint('更新校验未通过：${failure.name}');
      await _deleteQuietly(target);
      state = state.copyWith(stage: UpdateStage.failed, failure: failure);
      return;
    }
    state = state.copyWith(stage: UpdateStage.readyToInstall, clearFailure: true);
  }

  Future<File?> _targetFile() async {
    final artifact = state.decision?.artifact;
    if (artifact == null) {
      return null;
    }
    try {
      final directory = await _deps.loadUpdatesDirectory();
      if (!directory.existsSync()) {
        directory.createSync(recursive: true);
      }
      return File('${directory.path}${Platform.pathSeparator}${artifact.id}.apk');
    } on Object catch (error) {
      debugPrint('更新暂存目录不可用：$error');
      return null;
    }
  }

  Future<LocalVersion?> _safeLocalVersion(UpdateDependencies deps) async {
    try {
      return await deps.loadLocalVersion();
    } on Object {
      return null;
    }
  }

  Future<bool> _safeIsOnWifi() async {
    try {
      return await _deps.installer.isOnWifi();
    } on UpdatePlatformException {
      return true;
    }
  }

  bool _shouldAutoCheck(PrefsStore prefs) {
    final last = prefs.updateLastCheckAtMillis();
    if (last == null) {
      return true;
    }
    final elapsed = DateTime.now().millisecondsSinceEpoch - last;
    return elapsed >= autoCheckInterval.inMilliseconds;
  }

  /// 升级后回收：已安装版本号越过被忽略的版本 → 清掉忽略态。
  Future<void> _recoverAfterUpgrade(PrefsStore prefs) async {
    final ignored = prefs.ignoredUpdateVersionCode();
    if (ignored == null) {
      return;
    }
    int installed = 0;
    try {
      installed = await _deps.installer.installedVersionCode();
    } on UpdatePlatformException {
      return;
    }
    final current = state.localVersion?.versionCode ?? 0;
    final effective = installed > 0 ? installed : current;
    if (effective > 0 && ignored <= effective) {
      await prefs.clearIgnoredUpdateVersionCode();
    }
  }

  Future<void> _cleanResidualFiles() async {
    try {
      final directory = await _deps.loadUpdatesDirectory();
      if (!directory.existsSync()) {
        return;
      }
      for (final entity in directory.listSync()) {
        if (entity is File) {
          await _deleteQuietly(entity);
        }
      }
    } on Object {
      return;
    }
  }

  Future<void> _deleteQuietly(File file) async {
    try {
      if (file.existsSync()) {
        await file.delete();
      }
    } on FileSystemException {
      return;
    }
  }
}
