// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'riverpod_sample.dart';

// **************************************************************************
// RiverpodGenerator
// **************************************************************************

// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint, type=warning
/// APP-001 样例：Riverpod 独占本文件（一文件一生成器）。

@ProviderFor(scaffoldSampleLabel)
final scaffoldSampleLabelProvider = ScaffoldSampleLabelProvider._();

/// APP-001 样例：Riverpod 独占本文件（一文件一生成器）。

final class ScaffoldSampleLabelProvider
    extends $FunctionalProvider<String, String, String>
    with $Provider<String> {
  /// APP-001 样例：Riverpod 独占本文件（一文件一生成器）。
  ScaffoldSampleLabelProvider._()
    : super(
        from: null,
        argument: null,
        retry: null,
        name: r'scaffoldSampleLabelProvider',
        isAutoDispose: true,
        dependencies: null,
        $allTransitiveDependencies: null,
      );

  @override
  String debugGetCreateSourceHash() => _$scaffoldSampleLabelHash();

  @$internal
  @override
  $ProviderElement<String> $createElement($ProviderPointer pointer) =>
      $ProviderElement(pointer);

  @override
  String create(Ref ref) {
    return scaffoldSampleLabel(ref);
  }

  /// {@macro riverpod.override_with_value}
  Override overrideWithValue(String value) {
    return $ProviderOverride(
      origin: this,
      providerOverride: $SyncValueProvider<String>(value),
    );
  }
}

String _$scaffoldSampleLabelHash() =>
    r'c252fb262d3d290f592420a8e4c3b43b409112a9';
