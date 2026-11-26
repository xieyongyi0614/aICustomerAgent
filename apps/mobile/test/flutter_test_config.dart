import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'support/tolerant_golden_comparator.dart';

Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  final comparator = goldenFileComparator;
  if (comparator is LocalFileComparator) {
    goldenFileComparator = TolerantGoldenComparator(comparator.basedir);
  }
  await testMain();
}
