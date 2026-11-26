import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/bootstrap.dart';

void main() {
  testWidgets('boot shell builds', (tester) async {
    expect(() => MobileApp(), returnsNormally);
  });
}
