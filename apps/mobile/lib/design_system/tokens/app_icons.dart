import 'package:flutter/widgets.dart';

/// Lucide 线性图标（codepoint 对齐 lucide_icons 包；自建 IconData 以兼容 Flutter 3.47+ 的 final IconData）。
class AppIcons {
  const AppIcons._();

  static const home = IconData(0xf35e, fontFamily: 'lucide');
  static const layoutGrid = IconData(0xf38a, fontFamily: 'lucide');
  static const messageCircle = IconData(0xf3cd, fontFamily: 'lucide');
  static const heart = IconData(0xf354, fontFamily: 'lucide');
  static const user = IconData(0xf564, fontFamily: 'lucide');
}
