import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/design_system/components/states/states.dart';

void main() {
  test('error copy has no technical details', () {
    for (final s in [
      StateCopy.networkError,
      StateCopy.timeout,
      StateCopy.unauthorized,
      StateCopy.badRequest,
      StateCopy.serverError,
      StateCopy.streamInterrupted,
      StateCopy.parseFailure,
    ]) {
      expect(s.contains(RegExp(r'\d{3}')), isFalse);
      expect(s.contains('Exception'), isFalse);
      expect(s.contains('Dio'), isFalse);
      expect(s.contains('status'), isFalse);
    }
  });

  test('error copy offers next action', () {
    expect(StateCopy.retryAction.isNotEmpty, isTrue);
  });
}
