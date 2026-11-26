import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

class TolerantGoldenComparator extends LocalFileComparator {
  TolerantGoldenComparator(Uri basedir, {this.tolerance = 0.002})
      : assert(tolerance >= 0 && tolerance <= 1),
        super(basedir.resolve('goldens.dart'));

  final double tolerance;

  @override
  Future<bool> compare(Uint8List imageBytes, Uri golden) async {
    final result = await GoldenFileComparator.compareLists(
      imageBytes,
      await getGoldenBytes(golden),
    );
    final passed = result.passed || result.diffPercent <= tolerance;
    if (passed) {
      result.dispose();
      return true;
    }
    final error = await generateFailureOutput(result, golden, basedir);
    result.dispose();
    throw FlutterError(error);
  }
}
