import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/app/update/update_sheet.dart';
import 'package:mobile/core/updater/apk_downloader.dart';
import 'package:mobile/core/updater/apk_installer.dart';
import 'package:mobile/core/updater/apk_verifier.dart';
import 'package:mobile/core/updater/release_api.dart';
import 'package:mobile/core/updater/update_providers.dart';
import 'package:mobile/features/profile/presentation/about_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

const _payload = 'ui-test-apk';
final _digest = sha256.convert(utf8.encode(_payload)).toString();
const _fingerprint = 'AB:CD:EF:01';
const _notes = '**粗体** 与 <b>标签</b> 都应原样显示';

class _FakePlatform implements UpdatePlatform {
  @override
  Future<String?> apkSignatureFingerprint(String apkPath) async => _fingerprint;

  @override
  Future<bool> canInstallPackages() async => true;

  @override
  Future<int> installedVersionCode() async => 10;

  @override
  Future<String?> installedSignatureFingerprint() async => _fingerprint;

  @override
  Future<bool> installApk(String apkPath) async => true;

  @override
  Future<bool> isOnWifi() async => true;

  @override
  Future<void> openInstallPermissionSettings() async {}
}

class _Adapter implements HttpClientAdapter {
  _Adapter({required this.forceUpdate});

  final bool forceUpdate;
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
    return Future.value(
      ResponseBody.fromString(
        jsonEncode({
          'has_update': true,
          'latest': {
            'version_name': '0.20.0',
            'version_code': 20,
            // 与服务端语义一致：min_supported 低于本地版本 → 推荐更新（非强制）
            'min_supported_version_code': 10,
            'force_update': forceUpdate,
            'release_notes': _notes,
            'published_at': '2026-10-09T00:00:00+00:00',
          },
          'artifacts': [
            {
              'id': 'art_1',
              'type': 'full',
              'url': '/api/v1/app-release/artifacts/art_1/download',
              'size_bytes': utf8.encode(_payload).length,
              'sha256': _digest,
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
  }
}

UpdateDependencies _deps(_Adapter adapter, {bool installSupported = true}) {
  final dio = Dio(BaseOptions(baseUrl: 'http://example.test/api/v1'));
  dio.httpClientAdapter = adapter;
  final installer = ApkInstaller(platform: _FakePlatform());
  return UpdateDependencies(
    api: ReleaseApi(dio: dio),
    downloader: ApkDownloader.withOpener(
      (url, {startByte, cancelToken}) async => ArtifactStreamResponse(
        statusCode: 200,
        stream: Stream.fromIterable([utf8.encode(_payload)]),
      ),
    ),
    verifier: ApkVerifier(installer: installer),
    installer: installer,
    loadLocalVersion: () async =>
        const LocalVersion(versionCode: 10, versionName: '0.10.0'),
    loadUpdatesDirectory: () async =>
        Directory('${Directory.systemTemp.path}/updater-ui-test'),
    installSupported: installSupported,
  );
}

Future<ProviderContainer> _containerFor(
  WidgetTester tester,
  _Adapter adapter, {
  bool installSupported = true,
}) async {
  final container = ProviderContainer(
    overrides: [
      updateDependenciesProvider.overrideWithValue(
        _deps(adapter, installSupported: installSupported),
      ),
    ],
  );
  addTearDown(container.dispose);
  // widget 测试的时钟是假的：真实 I/O（prefs / 网络替身 / 文件）必须走 runAsync。
  await tester.runAsync(
    () => container.read(updateControllerProvider.notifier).check(manual: true),
  );
  return container;
}

Widget _host(ProviderContainer container, Widget child) {
  return UncontrolledProviderScope(
    container: container,
    child: MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(body: child),
    ),
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('test_force_sheet_hides_dismiss_paths', (tester) async {
    final container = await _containerFor(tester, _Adapter(forceUpdate: true));
    await tester.pumpWidget(_host(container, const UpdateSheet()));
    await tester.pumpAndSettle();

    expect(find.text('这个版本需要更新'), findsOneWidget);
    expect(find.text('立即更新'), findsOneWidget);
    expect(find.text('稍后再说'), findsNothing);
    expect(find.text('忽略这个版本'), findsNothing);
  });

  testWidgets('test_recommend_sheet_exposes_later_and_ignore', (tester) async {
    final container = await _containerFor(tester, _Adapter(forceUpdate: false));
    await tester.pumpWidget(_host(container, const UpdateSheet()));
    await tester.pumpAndSettle();

    expect(find.text('新版本准备好了'), findsOneWidget);
    expect(find.text('稍后再说'), findsOneWidget);
    expect(find.text('忽略这个版本'), findsOneWidget);
  });

  testWidgets('test_release_notes_render_as_plain_text', (tester) async {
    final container = await _containerFor(tester, _Adapter(forceUpdate: false));
    await tester.pumpWidget(_host(container, const UpdateSheet()));
    await tester.pumpAndSettle();

    expect(find.text(_notes), findsOneWidget);
    expect(find.byType(RichText), findsWidgets);
  });

  testWidgets('test_version_line_uses_tabular_figures', (tester) async {
    final container = await _containerFor(tester, _Adapter(forceUpdate: false));
    await tester.pumpWidget(_host(container, const UpdateSheet()));
    await tester.pumpAndSettle();

    final versionText = tester.widget<Text>(find.text('v0.10.0 → v0.20.0'));
    expect(versionText.style?.fontFeatures, contains(const FontFeature.tabularFigures()));
  });

  testWidgets('test_download_reaches_ready_to_install_state', (tester) async {
    final container = await _containerFor(tester, _Adapter(forceUpdate: false));
    final controller = container.read(updateControllerProvider.notifier);
    await tester.runAsync(controller.startDownload);
    await tester.pumpWidget(_host(container, const UpdateSheet()));
    await tester.pumpAndSettle();

    expect(find.text('安装包准备好了'), findsOneWidget);
    expect(find.text('去安装'), findsOneWidget);
  });

  testWidgets('test_dev_flavor_hides_install_button', (tester) async {
    final container = await _containerFor(
      tester,
      _Adapter(forceUpdate: false),
      installSupported: false,
    );
    await tester.pumpWidget(_host(container, const UpdateSheet()));
    await tester.pumpAndSettle();

    expect(find.text('前往发布页下载'), findsOneWidget);
    expect(find.text('立即更新'), findsNothing);
    expect(
      find.text('开发版本只做检测，安装包请到发布页下载'),
      findsOneWidget,
    );
  });

  testWidgets('test_about_page_shows_real_version_and_reserved_notice',
      (tester) async {
    final adapter = _Adapter(forceUpdate: false);
    final container = await _containerFor(tester, adapter);
    await tester.pumpWidget(_host(container, const AboutPage()));
    await tester.pumpAndSettle();

    expect(find.text('关于'), findsOneWidget);
    expect(find.text('0.10.0（10）'), findsOneWidget);
    expect(find.text('检查更新'), findsOneWidget);
    expect(find.text('仅 Wi-Fi 下载'), findsOneWidget);
    expect(find.text('备案号 / 软件著作权公示位（待 PLT-002 填写）'), findsOneWidget);
    expect(
      find.text('这个版本更新了什么'),
      findsOneWidget,
      reason: '有更新时应展示更新说明区',
    );
  });

  testWidgets('test_about_page_manual_check_hits_endpoint', (tester) async {
    final adapter = _Adapter(forceUpdate: false);
    final container = await _containerFor(tester, adapter);
    final before = adapter.seen.length;
    await tester.pumpWidget(_host(container, const AboutPage()));
    await tester.pumpAndSettle();

    await tester.runAsync(
      () => container.read(updateControllerProvider.notifier).check(manual: true),
    );
    await tester.pumpAndSettle();
    expect(adapter.seen.length, greaterThan(before));
  });
}
