import 'package:freezed_annotation/freezed_annotation.dart';

part 'freezed_sample.freezed.dart';
part 'freezed_sample.g.dart';

/// APP-001 样例：Freezed 独占本文件（一文件一生成器）。
@freezed
abstract class ScaffoldFreezedSample with _$ScaffoldFreezedSample {
  const factory ScaffoldFreezedSample({required String id}) = _ScaffoldFreezedSample;

  factory ScaffoldFreezedSample.fromJson(Map<String, dynamic> json) =>
      _$ScaffoldFreezedSampleFromJson(json);
}
