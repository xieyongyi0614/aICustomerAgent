import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/orb/orb.dart';

void main() {
  Widget wrap(Orb orb) {
    return MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(body: Center(child: orb)),
    );
  }

  testWidgets('orb builds all states and sizes', (tester) async {
    for (final state in OrbVisualState.values) {
      for (final size in OrbSize.values) {
        await tester.pumpWidget(wrap(Orb(size: size, state: state)));
        await tester.pump(const Duration(milliseconds: 50));
        expect(find.byType(Orb), findsOneWidget);
        expect(find.bySemanticsLabel(Orb.semanticsLabel), findsOneWidget);
      }
    }
  });

  testWidgets('done completes without crash', (tester) async {
    await tester.pumpWidget(
      wrap(const Orb(size: OrbSize.lg, state: OrbVisualState.done)),
    );
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byType(Orb), findsOneWidget);
  });

  testWidgets('ticker stops when paused', (tester) async {
    await tester.pumpWidget(
      wrap(const Orb(size: OrbSize.md, state: OrbVisualState.idle, paused: true)),
    );
    await tester.pump(const Duration(milliseconds: 100));
    expect(tester.hasRunningAnimations, isFalse);
  });

  testWidgets('golden orb states', (tester) async {
    for (final size in [OrbSize.lg, OrbSize.md]) {
      for (final state in OrbVisualState.values) {
        await tester.pumpWidget(
          wrap(Orb(size: size, state: state, paused: true)),
        );
        await tester.pump(const Duration(milliseconds: 16));
        await expectLater(
          find.byType(Orb),
          matchesGoldenFile('goldens/orb_${size.name}_${state.name}.png'),
        );
      }
    }
  });
}
