import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

/// 静态断言：app_icons.dart 声明的每个 codepoint 都在 fonts/lucide.ttf 的
/// cmap 中——挡住"码点与字体脱节"的豆腐块缺陷（上次事故的回归闸）。
/// 纯 Dart 解析 cmap format 4，不依赖 fontTools/python。
Set<int> _fontCodepoints(Uint8List bytes) {
  final bd = ByteData.sublistView(bytes);
  final numTables = bd.getUint16(4);
  var cmapOffset = 0;
  for (var i = 0; i < numTables; i++) {
    final rec = 12 + i * 16;
    final tag = String.fromCharCodes(bytes.sublist(rec, rec + 4));
    if (tag == 'cmap') cmapOffset = bd.getUint32(rec + 8);
  }
  if (cmapOffset == 0) throw StateError('cmap 表缺失');
  final subtables = bd.getUint16(cmapOffset + 2);
  var sub = 0;
  for (var i = 0; i < subtables; i++) {
    final rec = cmapOffset + 4 + i * 8;
    final platform = bd.getUint16(rec);
    final encoding = bd.getUint16(rec + 2);
    if (platform == 3 && encoding == 1) {
      sub = cmapOffset + bd.getUint32(rec + 4);
    }
  }
  if (sub == 0) throw StateError('cmap(3,1) 子表缺失');
  final format = bd.getUint16(sub);
  if (format != 4) {
    throw StateError('cmap format $format 非预期（本解析器按 format 4）');
  }
  final segCount = bd.getUint16(sub + 6) ~/ 2;
  final endBase = sub + 14;
  final startBase = endBase + segCount * 2 + 2;
  final deltaBase = startBase + segCount * 2;
  final rangeBase = deltaBase + segCount * 2;
  final codes = <int>{};
  for (var seg = 0; seg < segCount; seg++) {
    final end = bd.getUint16(endBase + seg * 2);
    final start = bd.getUint16(startBase + seg * 2);
    final delta = bd.getUint16(deltaBase + seg * 2);
    final rangeOff = bd.getUint16(rangeBase + seg * 2);
    if (start == 0xFFFF) continue;
    for (var cp = start; cp <= end; cp++) {
      int glyph;
      if (rangeOff == 0) {
        glyph = (cp + delta) & 0xFFFF;
      } else {
        final addr = rangeBase + seg * 2 + rangeOff + (cp - start) * 2;
        glyph = bd.getUint16(addr);
        if (glyph != 0) glyph = (glyph + delta) & 0xFFFF;
      }
      if (glyph != 0) codes.add(cp);
    }
  }
  return codes;
}

void main() {
  final source = File(
    'lib/design_system/tokens/app_icons.dart',
  ).readAsStringSync();
  final pattern = RegExp(
    r"static const (\w+) = IconData\((0x[0-9a-fA-F]+), fontFamily: 'lucide'\);",
  );
  final declared = pattern.allMatches(source).toList();

  test('app_icons_declares_icons', () {
    expect(declared.length, greaterThan(30));
  });

  test('app_icons_codepoints_exist_in_font_cmap', () {
    final codes = _fontCodepoints(
      File('fonts/lucide.ttf').readAsBytesSync(),
    );
    final missing = <String>[];
    for (final m in declared) {
      final cp = int.parse(m.group(2)!);
      if (!codes.contains(cp)) {
        missing.add('${m.group(1)} (0x${cp.toRadixString(16)})');
      }
    }
    expect(missing, isEmpty, reason: '字体缺字形：$missing');
  });

  test('app_icons_codepoints_unique', () {
    final cps = declared.map((m) => int.parse(m.group(2)!)).toList();
    expect(cps.toSet().length, cps.length);
  });
}
