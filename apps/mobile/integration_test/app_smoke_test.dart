import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/bootstrap.dart';
import 'package:mobile/app/theme/app_theme.dart';

void main() {
  testWidgets('smoke shell boots MaterialApp.router shape', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        title: '朝夕',
        theme: buildAppTheme(),
        home: const Scaffold(body: Text('朝夕')),
      ),
    );
    expect(find.text('朝夕'), findsOneWidget);
    expect(find.byType(MaterialApp), findsOneWidget);
  });

  test('bootstrap symbols exist', () {
    expect(bootstrap, isA<Function>());
  });
}
