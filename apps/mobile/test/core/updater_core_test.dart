import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/updater/apk_downloader.dart';
import 'package:mobile/core/updater/apk_installer.dart';
import 'package:mobile/core/updater/apk_verifier.dart';
import 'package:mobile/core/updater/release_api.dart';
import 'package:mobile/core/updater/release_models.dart';
import 'package:mobile/core/updater/update_checker.dart';

const _payload = 'apk-bytes-for-update-verification';
final _payloadDigest = sha256.convert(utf8.encode(_payload)).toString();
const _fingerprint = 'AA:BB:CC:DD';

ReleaseArtifact _artifact({
  String id = 'art_1',
  String type = fullArtifactType,
  int? sizeBytes,
  String? sha256Hex,
  int? fromVersionCode,
}) {
  final bytes = utf8.encode(_payload);
  return ReleaseArtifact(
    id: id,
    type: type,
    url: '/api/v1/app-release/artifacts/$id/download',
    sizeBytes: sizeBytes ?? bytes.length,
    sha256: sha256Hex ?? _payloadDigest,
    signatureFingerprint: _fingerprint,
    fromVersionCode: fromVersionCode,
  );
}

ReleaseInfo _latest({
  int versionCode = 20,
  int minSupported = 18,
  bool forceUpdate = false,
}) =>
    ReleaseInfo(
      versionName: '0.$versionCode.0',
      versionCode: versionCode,
      minSupportedVersionCode: minSupported,
      forceUpdate: forceUpdate,
      releaseNotes: '# 更新\n- 纯文本',
    );

UpdateCheckResult _result({
  bool hasUpdate = true,
  ReleaseInfo? latest,
  List<ReleaseArtifact>? artifacts,
}) =>
    UpdateCheckResult(
      hasUpdate: hasUpdate,
      latest: latest ?? (hasUpdate ? _latest() : null),
      artifacts: artifacts ?? [_artifact()],
    );

class _FakePlatform implements UpdatePlatform {
  _FakePlatform({
    this.apkFingerprint = _fingerprint,
    this.selfFingerprint = _fingerprint,
    this.installedCode = 0,
    this.canInstall = true,
    this.wifi = true,
    this.installLaunched = true,
  });

  String? apkFingerprint;
  String? selfFingerprint;
  int installedCode;
  bool canInstall;
  bool wifi;
  bool installLaunched;
  int installCalls = 0;

  @override
  Future<String?> apkSignatureFingerprint(String apkPath) async => apkFingerprint;

  @override
  Future<bool> canInstallPackages() async => canInstall;

  @override
  Future<int> installedVersionCode() async => installedCode;

  @override
  Future<String?> installedSignatureFingerprint() async => selfFingerprint;

  @override
  Future<bool> installApk(String apkPath) async {
    installCalls += 1;
    return installLaunched;
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

Dio _dioWith(_FakeAdapter adapter) {
  final dio = Dio(BaseOptions(baseUrl: 'http://example.test/api/v1'));
  dio.httpClientAdapter = adapter;
  return dio;
}

void main() {
  group('models', () {
    test('test_normalize_fingerprint_is_uppercase_and_colon_separated', () {
      expect(
        normalizeFingerprint('aabbccddeeff0011'),
        'AA:BB:CC:DD:EE:FF:00:11',
      );
      expect(normalizeFingerprint('AA:BB:CC:DD'), 'AA:BB:CC:DD');
      expect(normalizeFingerprint(''), '');
    });

    test('test_release_artifact_requires_sha256_and_positive_size', () {
      expect(
        ReleaseArtifact.tryParse({
          'id': 'a',
          'type': 'full',
          'url': '/x',
          'size_bytes': 10,
          'sha256': 'abc',
        }),
        isNull,
        reason: 'sha256 长度不足 → 该制品不可用',
      );
      expect(
        ReleaseArtifact.tryParse({
          'id': 'a',
          'type': 'full',
          'url': '/x',
          'size_bytes': 0,
          'sha256': _payloadDigest,
        }),
        isNull,
      );
      expect(
        ReleaseArtifact.tryParse({
          'id': 'a',
          'type': 'full',
          'url': '/x',
          'size_bytes': 10,
          'sha256': _payloadDigest,
        }),
        isNotNull,
      );
    });

    test('test_update_check_result_parses_has_update_false_shape', () {
      final parsed = UpdateCheckResult.parse({
        'has_update': false,
        'latest': null,
        'artifacts': <Object>[],
      });
      expect(parsed.hasUpdate, isFalse);
      expect(parsed.latest, isNull);
      expect(parsed.artifacts, isEmpty);
    });
  });

  group('decideUpdate', () {
    test('test_decide_force_when_below_min_supported', () {
      final decision = decideUpdate(
        result: _result(latest: _latest(versionCode: 20, minSupported: 19)),
        localVersionCode: 18,
      );
      expect(decision.strategy, UpdateStrategy.force);
      expect(decision.installable, isTrue);
    });

    test('test_decide_force_when_server_flagged', () {
      final decision = decideUpdate(
        result: _result(latest: _latest(versionCode: 20, forceUpdate: true)),
        localVersionCode: 19,
      );
      expect(decision.strategy, UpdateStrategy.force);
    });

    test('test_decide_recommend_when_outdated', () {
      final decision = decideUpdate(
        result: _result(latest: _latest(versionCode: 20, minSupported: 18)),
        localVersionCode: 19,
      );
      expect(decision.strategy, UpdateStrategy.recommend);
      expect(decision.dismissible, isTrue);
    });

    test('test_decide_none_when_up_to_date', () {
      final decision = decideUpdate(
        result: _result(latest: _latest(versionCode: 20)),
        localVersionCode: 20,
      );
      expect(decision.strategy, UpdateStrategy.none);
      expect(decision.artifact, isNull);
    });

    test('test_decide_none_when_has_update_false', () {
      final decision = decideUpdate(
        result: _result(hasUpdate: false, artifacts: []),
        localVersionCode: 1,
      );
      expect(decision.strategy, UpdateStrategy.none);
    });

    test('test_decide_honours_ignored_version_but_not_next_one', () {
      final ignored = decideUpdate(
        result: _result(latest: _latest(versionCode: 20)),
        localVersionCode: 19,
        ignoredVersionCode: 20,
      );
      expect(ignored.strategy, UpdateStrategy.none);

      final next = decideUpdate(
        result: _result(latest: _latest(versionCode: 21, minSupported: 18)),
        localVersionCode: 19,
        ignoredVersionCode: 20,
      );
      expect(next.strategy, UpdateStrategy.recommend);
    });

    test('test_unknown_artifact_type_is_ignored_not_guessed', () {
      final decision = decideUpdate(
        result: _result(
          artifacts: [
            _artifact(id: 'patch_1', type: 'patch', fromVersionCode: 12),
            _artifact(id: 'full_1'),
          ],
        ),
        localVersionCode: 10,
      );
      expect(decision.artifact?.id, 'full_1');
      expect(decision.artifact?.type, fullArtifactType);
    });

    test('test_patch_only_yields_no_applicable_artifact', () {
      final decision = decideUpdate(
        result: _result(
          artifacts: [_artifact(id: 'patch_1', type: 'patch', fromVersionCode: 12)],
        ),
        localVersionCode: 10,
      );
      expect(decision.strategy, UpdateStrategy.none);
      expect(decision.failure, UpdateFailureKind.noApplicableArtifact);
    });

    test('test_multiple_full_picks_first', () {
      final decision = decideUpdate(
        result: _result(
          artifacts: [_artifact(id: 'full_1'), _artifact(id: 'full_2')],
        ),
        localVersionCode: 10,
      );
      expect(decision.artifact?.id, 'full_1');
    });
  });

  group('apk_downloader', () {
    late Directory dir;

    setUp(() async {
      dir = await Directory.systemTemp.createTemp('updater-download-');
    });

    tearDown(() async {
      if (dir.existsSync()) {
        await dir.delete(recursive: true);
      }
    });

    test('test_download_writes_full_body_and_reports_progress', () async {
      final bytes = utf8.encode(_payload);
      final downloader = ApkDownloader.withOpener(
        (url, {startByte, cancelToken}) async => ArtifactStreamResponse(
          statusCode: 200,
          stream: Stream.fromIterable(bytes.map((b) => [b])),
        ),
      );
      final target = File('${dir.path}/a.apk');
      final progress = <int>[];
      final outcome = await downloader.download(
        artifact: _artifact(sizeBytes: bytes.length),
        target: target,
        onProgress: (received, total) => progress.add(received),
      );
      expect(outcome.ok, isTrue);
      expect(await target.readAsBytes(), bytes);
      expect(progress.last, bytes.length);
    });

    test('test_download_resumes_with_range_and_appends', () async {
      final bytes = utf8.encode(_payload);
      final target = File('${dir.path}/r.apk');
      await target.writeAsBytes(bytes.sublist(0, 5));
      int? requestedStart;
      final downloader = ApkDownloader.withOpener(
        (url, {startByte, cancelToken}) async {
          requestedStart = startByte;
          return ArtifactStreamResponse(
            statusCode: 206,
            stream: Stream.fromIterable([bytes.sublist(5)]),
          );
        },
      );
      final outcome = await downloader.download(
        artifact: _artifact(sizeBytes: bytes.length),
        target: target,
      );
      expect(requestedStart, 5);
      expect(outcome.ok, isTrue);
      expect(await target.readAsBytes(), bytes);
    });

    test('test_download_truncates_when_server_ignores_range', () async {
      final bytes = utf8.encode(_payload);
      final target = File('${dir.path}/t.apk');
      await target.writeAsBytes(utf8.encode('stale-broken-prefix'));
      final downloader = ApkDownloader.withOpener(
        (url, {startByte, cancelToken}) async => ArtifactStreamResponse(
          statusCode: 200,
          stream: Stream.fromIterable([bytes]),
        ),
      );
      final outcome = await downloader.download(
        artifact: _artifact(sizeBytes: bytes.length),
        target: target,
      );
      expect(outcome.ok, isTrue);
      expect(
        await target.readAsBytes(),
        bytes,
        reason: '服务端回 200 全量体时必须截断重写，否则拼出损坏文件',
      );
    });

    test('test_download_maps_api_failure_kind', () async {
      final downloader = ApkDownloader.withOpener(
        (url, {startByte, cancelToken}) async =>
            throw const UpdateApiException(UpdateFailureKind.network),
      );
      final outcome = await downloader.download(
        artifact: _artifact(),
        target: File('${dir.path}/f.apk'),
      );
      expect(outcome.ok, isFalse);
      expect(outcome.failure, UpdateFailureKind.network);
    });
  });

  group('apk_verifier', () {
    late Directory dir;

    setUp(() async {
      dir = await Directory.systemTemp.createTemp('updater-verify-');
    });

    tearDown(() async {
      if (dir.existsSync()) {
        await dir.delete(recursive: true);
      }
    });

    Future<File> writeApk([String content = _payload]) async {
      final file = File('${dir.path}/v.apk');
      await file.writeAsBytes(utf8.encode(content));
      return file;
    }

    test('test_verify_passes_when_size_hash_and_signature_match', () async {
      final verifier = ApkVerifier(
        installer: ApkInstaller(platform: _FakePlatform()),
      );
      final failure = await verifier.verify(
        file: await writeApk(),
        artifact: _artifact(),
      );
      expect(failure, isNull);
    });

    test('test_verify_rejects_size_mismatch_as_incomplete', () async {
      final verifier = ApkVerifier(
        installer: ApkInstaller(platform: _FakePlatform()),
      );
      final failure = await verifier.verify(
        file: await writeApk(),
        artifact: _artifact(sizeBytes: 9999),
      );
      expect(failure, UpdateFailureKind.incomplete);
    });

    test('test_verify_rejects_tampered_content', () async {
      final verifier = ApkVerifier(
        installer: ApkInstaller(platform: _FakePlatform()),
      );
      final file = await writeApk('tampered-content-with-same-length!!');
      final failure = await verifier.verify(
        file: file,
        artifact: _artifact(
          sizeBytes: await file.length(),
          sha256Hex: _payloadDigest,
        ),
      );
      expect(failure, UpdateFailureKind.hashMismatch);
    });

    test('test_verify_rejects_signature_mismatch', () async {
      final verifier = ApkVerifier(
        installer: ApkInstaller(
          platform: _FakePlatform(apkFingerprint: 'AA:BB:CC:DD:EE'),
        ),
      );
      final file = await writeApk();
      final failure = await verifier.verify(
        file: file,
        artifact: _artifact(sizeBytes: await file.length()),
      );
      expect(failure, UpdateFailureKind.signatureMismatch);
    });
  });

  group('release_api', () {
    test('test_fetch_latest_sends_params_and_parses_payload', () async {
      final adapter = _FakeAdapter(
        (options) async => ResponseBody.fromString(
          jsonEncode({
            'has_update': true,
            'latest': {
              'version_name': '0.20.0',
              'version_code': 20,
              'min_supported_version_code': 18,
              'force_update': false,
              'release_notes': '说明',
              'published_at': '2026-10-09T00:00:00+00:00',
            },
            'artifacts': [
              {
                'id': 'art_1',
                'type': 'full',
                'url': '/api/v1/app-release/artifacts/art_1/download',
                'size_bytes': 12,
                'sha256': _payloadDigest,
                'signature_fingerprint': _fingerprint,
                'from_version_code': null,
              },
            ],
          }),
          200,
          headers: {
            Headers.contentTypeHeader: ['application/json'],
          },
        ),
      );
      final api = ReleaseApi(dio: _dioWith(adapter));
      final result = await api.fetchLatest(
        platform: 'android',
        channel: 'prod',
        versionCode: 19,
      );
      expect(adapter.seen.single.path, '/app-release/latest');
      expect(adapter.seen.single.queryParameters, {
        'platform': 'android',
        'channel': 'prod',
        'version_code': 19,
      });
      expect(result.hasUpdate, isTrue);
      expect(result.latest?.versionCode, 20);
      expect(result.artifacts.single.id, 'art_1');
    });

    test('test_stream_opener_sends_range_and_strips_api_prefix', () async {
      final adapter = _FakeAdapter(
        (options) async => ResponseBody(
          Stream.value(Uint8List.fromList(utf8.encode('tail'))),
          206,
        ),
      );
      final api = ReleaseApi(dio: _dioWith(adapter));
      final response = await api.streamOpener()(
        '/api/v1/app-release/artifacts/art_1/download',
        startByte: 5,
      );
      expect(adapter.seen.single.path, '/app-release/artifacts/art_1/download');
      expect(adapter.seen.single.headers['Range'], 'bytes=5-');
      expect(adapter.seen.single.responseType, ResponseType.stream);
      expect(response.statusCode, 206);
    });

    test('test_request_path_keeps_absolute_urls_route_only', () {
      final api = ReleaseApi(dio: _dioWith(_FakeAdapter((_) async {
        return ResponseBody.fromString('{}', 200);
      })));
      expect(
        api.requestPath('http://host/api/v1/app-release/artifacts/x/download'),
        '/app-release/artifacts/x/download',
      );
      expect(api.requestPath('/other/path'), '/other/path');
    });
  });
}
