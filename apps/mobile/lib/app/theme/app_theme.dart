import 'package:flutter/material.dart';

/// APP-001 只留装配骨架；token 与 M3 覆盖层在 APP-002 落地。
ThemeData buildAppTheme() {
  return ThemeData(
    useMaterial3: true,
    colorScheme: const ColorScheme.light(),
  );
}
