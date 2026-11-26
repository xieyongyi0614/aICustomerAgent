import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// L1/L2/L3 + 骨架完整性静态断言（源码文本扫描，零新依赖）。
void main() {
  final libRoot = Directory('lib');

  List<File> dartFiles(String prefix) {
    return libRoot
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('.dart'))
        .where((f) => f.path.replaceAll('\\', '/').contains(prefix))
        .toList();
  }

  String read(File f) => f.readAsStringSync();

  test('test_layer_dirs_exist', () {
    for (final path in [
      'lib/app/router',
      'lib/app/theme',
      'lib/app/update',
      'lib/core/network',
      'lib/core/storage',
      'lib/design_system/tokens',
      'lib/design_system/components',
      'lib/design_system/orb',
    ]) {
      expect(Directory(path).existsSync(), isTrue, reason: path);
    }
    for (final domain in [
      'home',
      'chat',
      'life',
      'ledger',
      'car',
      'album',
      'memory',
      'briefing',
      'profile',
    ]) {
      for (final layer in ['data', 'domain', 'presentation']) {
        final path = 'lib/features/$domain/$layer';
        expect(Directory(path).existsSync(), isTrue, reason: path);
      }
    }
  });

  test('test_no_cross_feature_import', () {
    for (final file in dartFiles('lib/features/')) {
      final content = read(file);
      final match = RegExp(r'''feature[s]?/([a-z_]+)/''').firstMatch(content);
      if (match == null) continue;
      final own = RegExp(r'''lib/features/([a-z_]+)/''').firstMatch(file.path.replaceAll('\\', '/'));
      final ownDomain = own?.group(1);
      final all = RegExp(r'''package:mobile/features/([a-z_]+)/|features/([a-z_]+)/''')
          .allMatches(content);
      for (final m in all) {
        final other = m.group(1) ?? m.group(2);
        if (other != null && other != ownDomain) {
          fail('${file.path} imports features/$other (L1 cross-feature)');
        }
      }
    }
  });

  test('test_design_system_has_no_core_or_features_import', () {
    for (final file in dartFiles('lib/design_system/')) {
      final content = read(file);
      expect(content.contains("import 'package:mobile/core/"), isFalse,
          reason: '${file.path} imports core (L2)');
      expect(content.contains("import '../core/"), isFalse, reason: file.path);
      expect(content.contains("import '../../core/"), isFalse, reason: file.path);
      expect(content.contains('features/'), isFalse,
          reason: '${file.path} references features (L2)');
    }
  });

  test('test_core_does_not_import_features', () {
    for (final file in dartFiles('lib/core/')) {
      final content = read(file);
      expect(RegExp(r'''features/''').hasMatch(content), isFalse,
          reason: '${file.path} imports features');
    }
  });

  test('test_features_presentation_does_not_import_dio', () {
    for (final file in dartFiles('lib/features/')) {
      if (!file.path.replaceAll('\\', '/').contains('/presentation/')) continue;
      expect(read(file).contains('package:dio'), isFalse, reason: file.path);
    }
  });

  test('test_no_hardcoded_color_outside_tokens', () {
    for (final file in dartFiles('lib/')) {
      final normalized = file.path.replaceAll('\\', '/');
      if (normalized.contains('lib/design_system/tokens/')) continue;
      final content = read(file);
      expect(RegExp(r'Color\(0x').hasMatch(content), isFalse, reason: file.path);
      expect(RegExp(r'\bColors\.').hasMatch(content), isFalse, reason: file.path);
    }
  });

  test('test_no_unknown_font_weight_constant', () {
    for (final file in dartFiles('lib/')) {
      final content = read(file);
      for (final bad in ['FontWeight.w550', 'FontWeight.w650', 'FontWeight.w750']) {
        expect(content.contains(bad), isFalse, reason: '${file.path} has $bad');
      }
    }
  });

  test('test_single_generator_per_source_file', () {
    for (final file in dartFiles('lib/')) {
      final content = read(file);
      final hasFreezed = content.contains('@freezed') || content.contains('freezed_annotation');
      final hasDrift = content.contains('package:drift/drift.dart') ||
          content.contains('@DriftDatabase') ||
          content.contains('extends Table');
      final hasRiverpodGen = content.contains('riverpod_annotation') || content.contains('@riverpod');
      final count = [hasFreezed, hasDrift, hasRiverpodGen].where((e) => e).length;
      expect(count, lessThanOrEqualTo(1),
          reason: '${file.path} mixes generators (one file one generator)');
    }
  });

  test('test_drift_sample_output_suffix_is_drift_dart', () {
    final source = read(File('lib/core/scaffold_samples/drift_sample.dart'));
    expect(source.contains("part 'drift_sample.drift.dart';"), isTrue);
    expect(source.contains("part 'drift_sample.g.dart';"), isFalse);
  });

  /// D18 决策（`requirements-analysis.md` §6.1）：「仅本机」必须有可验证约束
  /// ——相册域全程零网络，静态扫描整域（既有守卫只覆盖 presentation 层）。
  test('test_album_feature_has_no_network_access', () {
    for (final file in dartFiles('lib/features/album/')) {
      final content = read(file);
      expect(content.contains('package:dio'), isFalse, reason: file.path);
      expect(content.contains('core/network'), isFalse, reason: file.path);
      expect(content.contains('http://'), isFalse, reason: file.path);
      expect(content.contains('https://'), isFalse, reason: file.path);
    }
  });

  /// `progress-audit` §7.6：`LocalStores` / drift 表是服务端 DTO 投影且运行时
  /// 零接线；相册元数据不得复用该死通道（`APP-034` §4.2 裁决 3）。
  test('test_album_never_imports_local_stores', () {
    for (final file in dartFiles('lib/features/album/')) {
      final content = read(file);
      expect(content.contains('local_stores.dart'), isFalse, reason: file.path);
      expect(content.contains('cache_db.dart'), isFalse, reason: file.path);
    }
  });
}
