import 'package:flutter/material.dart';

import '../../design_system/tokens/tokens.dart';

export '../../design_system/tokens/tokens.dart';

extension AppThemeAccess on BuildContext {
  AppColors get colors => Theme.of(this).extension<AppColors>()!;
  AppGradients get gradients => Theme.of(this).extension<AppGradients>()!;
  AppRadii get radii => Theme.of(this).extension<AppRadii>()!;
  AppTypography get typography => Theme.of(this).extension<AppTypography>()!;
  AppElevation get elevation => Theme.of(this).extension<AppElevation>()!;
  AppSpacing get spacing => Theme.of(this).extension<AppSpacing>()!;
  AppMotion get motion => Theme.of(this).extension<AppMotion>()!;
}
