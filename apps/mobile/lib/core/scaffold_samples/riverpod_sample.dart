import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'riverpod_sample.g.dart';

/// APP-001 样例：Riverpod 独占本文件（一文件一生成器）。
@riverpod
String scaffoldSampleLabel(Ref ref) => 'scaffold';
