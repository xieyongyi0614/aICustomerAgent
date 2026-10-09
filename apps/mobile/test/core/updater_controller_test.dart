import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/env/app_env.dart';
import 'package:mobile/core/storage/prefs_store.dart';
import 'package:mobile/core/updater/apk_downloader.dart';
import 'package:mobile/core/updater/apk_installer.dart';
import 'package:mobile/core/updater/apk_verifier.dart';
import 'package:mobile/core/updater/release_api.dart';
import 'package:mobile/core/updater/release_models.dart';
import 'package:mobile/core/updater/update_providers.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _payload = 'controller-flow-apk-bytes';
final _digest = sha256.convert(utf8.encode(_payload)).toString();
const _fingerprint = 'AB:CD:EF:01';

class _FakePlatform implements UpdatePlatform {
  _FakePlatform({
    this.installedCode = 10,
    this.canInstall = true,
    this.wifi = true,
  });

  int installedCode;
  bool canInstall;
  bool wifi;
  int installCalls = 0;

  @override
  Future<String?> apkSignatureFingerprint(String apkPath) async => _fingerprint;

  @override
  Future<bool> canInstallPackages() async => canInstall;

  @override
  Future<int> installedVersionCode() async => installedCode;

  @override
  Future<String?> installedSignatureFingerprint() async => _fingerprint;

  @override
  Future<bool> installApk(String apkPath) async {
    installCalls += 1;
    return true;
  }

  @override
  Future<bool> isOnWifi() async => wifi;

  @override
  Future<void> openInstallPermissionSettings() async {}
}

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.handler);

  final Future<ResponseBody> Function(RequestOptions options) handler;
  final List<RequestOptions> seen = [];

  @override
  void close({bool force = false}) {}

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) {
    seen.add(options);
    return handler(options);
  }
}

class _Harness {
  _Harness({
    int localVersionCode = 10,
    int latestVersionCode = 20,
    // 缺省走「推荐更新」路径（min_supported 不高于本地版本）；强制更新单独用 minSupported 覆盖
    int minSupported = 10,
    bool forceUpdate = false,
    List<Map<String, Object?>>? artifacts,
    bool installSupported = true,
    _FakePlatform? platform,
  })  : platform = platform ?? _FakePlatform(installedCode: localVersionCode),
        adapter = _FakeAdapter(
          (options) async => ResponseBody.fromString(
            jsonEncode({
              'has_update': latestVersionCode > localVersionCode,
              'latest': latestVersionCode > localVersionCode
                  ? {
                      'version_name': '0.$latestVersionCode.0',
                      'version_code': latestVersionCode,
                      'min_supported_version_code': minSupported,
                      'force_update': forceUpdate,
                      'release_notes': '更新说明',
                      'published_at': '2026-10-09T00:00:00+00:00',
                    }
                  : null,
              'artifacts': latestVersionCode > localVersionCode
                  ? (artifacts ??
                      [
                        {
                          'id': 'art_1',
                          'type': 'full',
                          'url':
                              '/api/v1/app-release/artifacts/art_1/download',
                          'size_bytes': utf8.encode(_payload).length,
                          'sha256': _digest,
                          'signature_fingerprint': _fingerprint,
                          'from_version_code': null,
                        },
                      ])
                  : <Map<String, Object?>>[],
            }),
            200,
            headers: {
              Headers.contentTypeHeader: ['application/json'],
            },
          ),
        ) {
    final dio = Dio(BaseOptions(baseUrl: 'http://example.test/api/v1'));
    dio.httpClientAdapter = adapter;
    api = ReleaseApi(dio: dio);
    installer = ApkInstaller(platform: this.platform);
    dependencies = UpdateDependencies(
      api: api,
      downloader: ApkDownloader.withOpener(
        (url, {startByte, cancelToken}) async => ArtifactStreamResponse(
          statusCode: startByte == null ? 200 : 206,
          stream: Stream.fromIterable([
            utf8.encode(_payload).sublist(startByte ?? 0),
          ]),
        ),
      ),
      verifier: ApkVerifier(installer: installer),
      installer: installer,
      loadLocalVersion: () async => LocalVersion(
        versionCode: localVersionCode,
        versionName: '0.$localVersionCode.0',
      ),
      loadUpdatesDirectory: () async => updatesDir,
      installSupported: installSupported,
    );
  }

  final _FakePlatform platform;
  final _FakeAdapter adapter;
  late final ReleaseApi api;
  late final ApkInstaller installer;
  late final UpdateDependencies dependencies;
  final Directory updatesDir =
      Directory('${Directory.systemTemp.path}/updater-controller-test');

  ProviderContainer container() {
    final value = ProviderContainer(
      overrides: [updateDependenciesProvider.overrideWithValue(dependencies)],
    );
    addTearDown(value.dispose);
    return value;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    final dir = Directory('${Directory.systemTemp.path}/updater-controller-test');
    if (dir.existsSync()) {
      await dir.delete(recursive: true);
    }
  });

  test('test_controller_marks_up_to_date_when_server_says_no_update', () async {
    final harness = _Harness(localVersionCode: 20, latestVersionCode: 20);
    final container = harness.container();
    await container.read(updateControllerProvider.notifier).check(manual: true);
    expect(container.read(updateControllerProvider).stage, UpdateStage.upToDate);
    final prefs = await PrefsStore.load();
    expect(prefs.updateLastCheckAtMillis(), isNotNull);
  });

  test('test_controller_first_run_checks_immediately', () async {
    final harness = _Harness();
    final container = harness.container();
    await container.read(updateControllerProvider.notifier).onStartup();
    expect(container.read(updateControllerProvider).stage, UpdateStage.available);
    expect(harness.adapter.seen.single.queryParameters!['channel'],
        AppEnv.flavor == 'prod' ? 'prod' : 'dev');
  });

  test('test_controller_throttles_auto_check_within_window', () async {
    final harness = _Harness();
    final prefs = await PrefsStore.load();
    await prefs.setUpdateLastCheckAtMillis(DateTime.now().millisecondsSinceEpoch);
    final container = harness.container();
    await container.read(updateControllerProvider.notifier).onStartup();
    expect(container.read(updateControllerProvider).stage, UpdateStage.idle);
    expect(harness.adapter.seen, isEmpty);
  });

  test('test_controller_manual_check_ignores_throttle', () async {
    final harness = _Harness();
    final prefs = await PrefsStore.load();
    await prefs.setUpdateLastCheckAtMillis(DateTime.now().millisecondsSinceEpoch);
    final container = harness.container();
    await container.read(updateControllerProvider.notifier).check(manual: true);
    expect(container.read(updateControllerProvider).stage, UpdateStage.available);
  });

  test('test_controller_ignore_persists_version_code', () async {
    final harness = _Harness();
    final container = harness.container();
    final controller = container.read(updateControllerProvider.notifier);
    await controller.check(manual: true);
    await controller.ignoreCurrentVersion();
    expect(container.read(updateControllerProvider).stage, UpdateStage.idle);
    final prefs = await PrefsStore.load();
    expect(prefs.ignoredUpdateVersionCode(), 20);
  });

  test('test_controller_startup_clears_stale_ignored_version', () async {
    final prefs = await PrefsStore.load();
    await prefs.setIgnoredUpdateVersionCode(10);
    final harness = _Harness(localVersionCode: 10);
    final container = harness.container();
    await container.read(updateControllerProvider.notifier).onStartup();
    expect((await PrefsStore.load()).ignoredUpdateVersionCode(), isNull);
  });

  test('test_controller_download_then_verify_reaches_ready_to_install',
      () async {
    final harness = _Harness();
    final container = harness.container();
    final deps = container.read(updateDependenciesProvider);
    expect(identical(deps.installer, harness.installer), isTrue);
    expect(
      identical(deps.verifier.installer, harness.installer),
      isTrue,
      reason: '校验器必须持有同一个安装器实例',
    );
    final controller = container.read(updateControllerProvider.notifier);
    await controller.check(manual: true);
    await controller.startDownload();
    final state = container.read(updateControllerProvider);
    expect(state.failure, isNull, reason: '下载与校验都应通过');
    expect(state.stage, UpdateStage.readyToInstall);
    final file = File('${harness.updatesDir.path}/art_1.apk');
    expect(file.existsSync(), isTrue);
    expect(await file.readAsString(), _payload);
  });

  test('test_controller_blocks_download_on_dev_flavor', () async {
    final harness = _Harness(installSupported: false);
    final container = harness.container();
    final controller = container.read(updateControllerProvider.notifier);
    await controller.check(manual: true);
    await controller.startDownload();
    expect(container.read(updateControllerProvider).stage, UpdateStage.available);
    expect(
      File('${harness.updatesDir.path}/art_1.apk').existsSync(),
      isFalse,
    );
  });

  test('test_controller_asks_before_using_cellular', () async {
    final harness = _Harness(platform: _FakePlatform(wifi: false));
    final container = harness.container();
    final controller = container.read(updateControllerProvider.notifier);
    await controller.check(manual: true);
    await controller.startDownload();
    expect(
      container.read(updateControllerProvider).stage,
      UpdateStage.confirmWifi,
    );
    await controller.confirmWifiAndDownload();
    expect(
      container.read(updateControllerProvider).stage,
      UpdateStage.readyToInstall,
    );
  });

  test('test_controller_requires_unknown_sources_permission', () async {
    final harness = _Harness(
      platform: _FakePlatform(canInstall: false),
    );
    final container = harness.container();
    final controller = container.read(updateControllerProvider.notifier);
    await controller.check(manual: true);
    await controller.startDownload();
    await controller.install();
    expect(
      container.read(updateControllerProvider).stage,
      UpdateStage.permissionRequired,
    );
    expect(harness.platform.installCalls, 0);
  });

  test('test_controller_install_launches_when_allowed', () async {
    final harness = _Harness();
    final container = harness.container();
    final controller = container.read(updateControllerProvider.notifier);
    await controller.check(manual: true);
    await controller.startDownload();
    await controller.install();
    expect(harness.platform.installCalls, 1);
    expect(
      container.read(updateControllerProvider).stage,
      UpdateStage.readyToInstall,
    );
  });

  test('test_controller_failed_network_maps_to_failure_kind', () async {
    final harness = _Harness();
    final dio = Dio(BaseOptions(baseUrl: 'http://example.test/api/v1'));
    dio.httpClientAdapter = _FakeAdapter(
      (options) async => throw DioException.connectionError(
        requestOptions: options,
        reason: 'offline',
      ),
    );
    final failing = ProviderContainer(
      overrides: [
        updateDependenciesProvider.overrideWithValue(
          UpdateDependencies(
            api: ReleaseApi(dio: dio),
            downloader: harness.dependencies.downloader,
            verifier: harness.dependencies.verifier,
            installer: harness.installer,
            loadLocalVersion: harness.dependencies.loadLocalVersion,
            loadUpdatesDirectory: harness.dependencies.loadUpdatesDirectory,
            installSupported: true,
          ),
        ),
      ],
    );
    addTearDown(failing.dispose);
    await failing.read(updateControllerProvider.notifier).check(manual: true);
    final state = failing.read(updateControllerProvider);
    expect(state.failure, UpdateFailureKind.network);
    expect(state.stage, UpdateStage.failed);
  });
}
