// 朝夕设计系统 · Token 模板
// 来源：zhaoxi-design-system skill（references/tokens.md 为数值真源）
// 首次拷入工程后必须过一遍 `flutter analyze`

import 'package:flutter/material.dart';

class AppColors extends ThemeExtension<AppColors> {
  const AppColors({
    required this.canvas,
    required this.surface,
    required this.ink,
    required this.ink2,
    required this.ink3,
    required this.line,
    required this.aiPrimary,
    required this.aiBlue,
    required this.aiCyan,
    required this.warm,
    required this.health,
    required this.heartFg,
    required this.money,
    required this.fillSubtle,
    required this.fillMuted,
    required this.trackBar,
    required this.borderDashed,
    required this.borderCheck,
    required this.toggleOff,
    required this.inkOnSoon,
    required this.onDeepPrimary,
    required this.onDeepSecondary,
    required this.onDeepTertiary,
    required this.bodyOnCard,
    required this.bodyOnBubble,
    required this.userBubbleBg,
    required this.userBubbleText,
    required this.bodyOnInsight,
    required this.privacyText,
    required this.onWhitePill,
    required this.avatarText,
    required this.tileAi,
    required this.tileHealth,
    required this.tileMoney,
    required this.tileWarm,
    required this.tileInfo,
    required this.tileTravel,
    required this.tileHeart,
    required this.tagPreferenceBg,
    required this.tagPreferenceFg,
    required this.tagHabitBg,
    required this.tagHabitFg,
    required this.tagGoalBg,
    required this.tagGoalFg,
    required this.tagRelationBg,
    required this.tagRelationFg,
    required this.danger,
    required this.dangerBg,
    required this.dangerText,
  });

  final Color canvas;
  final Color surface;
  final Color ink;
  final Color ink2;
  final Color ink3;
  final Color line;
  final Color aiPrimary;
  final Color aiBlue;
  final Color aiCyan;
  final Color warm;
  final Color health;

  /// 健康（心）图标前景（`tokens.md` §1.4：#F06A6A）——生活宫格「健康」格专用，
  /// 与青绿 `health`（健康域 / 完成态）不是同一语义，勿合并。
  final Color heartFg;
  final Color money;
  final Color fillSubtle;
  final Color fillMuted;
  final Color trackBar;
  final Color borderDashed;
  final Color borderCheck;
  final Color toggleOff;
  final Color inkOnSoon;
  final Color onDeepPrimary;
  final Color onDeepSecondary;
  final Color onDeepTertiary;
  final Color bodyOnCard;
  final Color bodyOnBubble;
  final Color userBubbleBg;
  final Color userBubbleText;
  final Color bodyOnInsight;
  final Color privacyText;
  final Color onWhitePill;
  final Color avatarText;
  final Color tileAi;
  final Color tileHealth;
  final Color tileMoney;
  final Color tileWarm;
  final Color tileInfo;
  final Color tileTravel;
  final Color tileHeart;
  final Color tagPreferenceBg;
  final Color tagPreferenceFg;
  final Color tagHabitBg;
  final Color tagHabitFg;
  final Color tagGoalBg;
  final Color tagGoalFg;
  final Color tagRelationBg;
  final Color tagRelationFg;

  /// 危险动作三件套（38 批量删除 / 61 删除按钮）：底 `rgba(240,106,106,.12)`
  /// 字 `#E05252`；`danger` 为底色同族的实色基线（深色模式取浅红）。
  final Color danger;
  final Color dangerBg;
  final Color dangerText;

  static const light = AppColors(
    canvas: Color(0xFFF5F4F0),
    surface: Color(0xFFFFFFFF),
    ink: Color(0xFF1B1C23),
    ink2: Color(0xFF6E7079),
    ink3: Color(0xFFA7A8B1),
    line: Color(0xFFECEAE3),
    aiPrimary: Color(0xFF7A5CFF),
    aiBlue: Color(0xFF3E8BFF),
    aiCyan: Color(0xFF2BD2E8),
    warm: Color(0xFFFF9D76),
    health: Color(0xFF33BC8C),
    heartFg: Color(0xFFF06A6A),
    money: Color(0xFFEFA63C),
    fillSubtle: Color(0xFFF3F2ED),
    fillMuted: Color(0xFFF1F0EA),
    trackBar: Color(0xFFF0EFE9),
    borderDashed: Color(0xFFDAD9D1),
    borderCheck: Color(0xFFD7D5CD),
    toggleOff: Color(0xFFDDDCD4),
    inkOnSoon: Color(0xFFB9B8AF),
    onDeepPrimary: Color(0xFFFFFFFF),
    onDeepSecondary: Color(0xB8FFFFFF),
    onDeepTertiary: Color(0xA6FFFFFF),
    bodyOnCard: Color(0xFF33343D),
    bodyOnBubble: Color(0xFF2C2D35),
    userBubbleBg: Color(0xFF1F222B),
    userBubbleText: Color(0xFFF4F4F7),
    bodyOnInsight: Color(0xFF3A3B45),
    privacyText: Color(0xFF2E7D5F),
    onWhitePill: Color(0xFF2B2A3D),
    avatarText: Color(0xFF7A3A1B),
    tileAi: Color(0x1F7A5CFF),
    tileHealth: Color(0x1F33BC8C),
    tileMoney: Color(0x24EFA63C),
    tileWarm: Color(0x29FF9D76),
    tileInfo: Color(0x1F3E8BFF),
    tileTravel: Color(0x212BD2E8),
    tileHeart: Color(0x1FFF6B6B),
    tagPreferenceBg: Color(0x1A7A5CFF),
    tagPreferenceFg: Color(0xFF7A5CFF),
    tagHabitBg: Color(0x24EFA63C),
    tagHabitFg: Color(0xFFC98418),
    tagGoalBg: Color(0x1F33BC8C),
    tagGoalFg: Color(0xFF24966E),
    tagRelationBg: Color(0x1F3E8BFF),
    tagRelationFg: Color(0xFF3E8BFF),
    danger: Color(0xFFE5484D),
    dangerBg: Color(0x1FF06A6A),
    dangerText: Color(0xFFE05252),
  );

  static const dark = AppColors(
    canvas: Color(0xFF191826),
    surface: Color(0xFF262445),
    ink: Color(0xFFF4F4F7),
    ink2: Color(0xB8FFFFFF),
    ink3: Color(0x8CFFFFFF),
    line: Color(0x1FFFFFFF),
    aiPrimary: Color(0xFF9B85FF),
    aiBlue: Color(0xFF6BA6FF),
    aiCyan: Color(0xFF4FE0F2),
    warm: Color(0xFFFFB093),
    health: Color(0xFF5AD2A6),
    heartFg: Color(0xFFFF8A8A),
    money: Color(0xFFF5BC63),
    fillSubtle: Color(0x14FFFFFF),
    fillMuted: Color(0x14FFFFFF),
    trackBar: Color(0x1FFFFFFF),
    borderDashed: Color(0x33FFFFFF),
    borderCheck: Color(0x33FFFFFF),
    toggleOff: Color(0x33FFFFFF),
    inkOnSoon: Color(0x66FFFFFF),
    onDeepPrimary: Color(0xFFFFFFFF),
    onDeepSecondary: Color(0xB8FFFFFF),
    onDeepTertiary: Color(0xA6FFFFFF),
    bodyOnCard: Color(0xFFE4E4EA),
    bodyOnBubble: Color(0xFFE4E4EA),
    userBubbleBg: Color(0xFF3A3550),
    userBubbleText: Color(0xFFF4F4F7),
    bodyOnInsight: Color(0xFFE4E4EA),
    privacyText: Color(0xFF7FD9B4),
    onWhitePill: Color(0xFF2B2A3D),
    avatarText: Color(0xFF7A3A1B),
    tileAi: Color(0x339B85FF),
    tileHealth: Color(0x335AD2A6),
    tileMoney: Color(0x33F5BC63),
    tileWarm: Color(0x33FFB093),
    tileInfo: Color(0x336BA6FF),
    tileTravel: Color(0x334FE0F2),
    tileHeart: Color(0x33FF8A8A),
    tagPreferenceBg: Color(0x339B85FF),
    tagPreferenceFg: Color(0xFF9B85FF),
    tagHabitBg: Color(0x33F5BC63),
    tagHabitFg: Color(0xFFF5BC63),
    tagGoalBg: Color(0x335AD2A6),
    tagGoalFg: Color(0xFF5AD2A6),
    tagRelationBg: Color(0x336BA6FF),
    tagRelationFg: Color(0xFF6BA6FF),
    danger: Color(0xFFFF8588),
    dangerBg: Color(0x29FF8588),
    dangerText: Color(0xFFFF8588),
  );

  @override
  AppColors copyWith({
    Color? canvas,
    Color? surface,
    Color? ink,
    Color? ink2,
    Color? ink3,
    Color? line,
    Color? aiPrimary,
    Color? aiBlue,
    Color? aiCyan,
    Color? warm,
    Color? health,
    Color? heartFg,
    Color? money,
    Color? fillSubtle,
    Color? fillMuted,
    Color? trackBar,
    Color? borderDashed,
    Color? borderCheck,
    Color? toggleOff,
    Color? inkOnSoon,
    Color? onDeepPrimary,
    Color? onDeepSecondary,
    Color? onDeepTertiary,
    Color? bodyOnCard,
    Color? bodyOnBubble,
    Color? userBubbleBg,
    Color? userBubbleText,
    Color? bodyOnInsight,
    Color? privacyText,
    Color? onWhitePill,
    Color? avatarText,
    Color? tileAi,
    Color? tileHealth,
    Color? tileMoney,
    Color? tileWarm,
    Color? tileInfo,
    Color? tileTravel,
    Color? tileHeart,
    Color? tagPreferenceBg,
    Color? tagPreferenceFg,
    Color? tagHabitBg,
    Color? tagHabitFg,
    Color? tagGoalBg,
    Color? tagGoalFg,
    Color? tagRelationBg,
    Color? tagRelationFg,
    Color? danger,
    Color? dangerBg,
    Color? dangerText,
  }) {
    return AppColors(
      canvas: canvas ?? this.canvas,
      surface: surface ?? this.surface,
      ink: ink ?? this.ink,
      ink2: ink2 ?? this.ink2,
      ink3: ink3 ?? this.ink3,
      line: line ?? this.line,
      aiPrimary: aiPrimary ?? this.aiPrimary,
      aiBlue: aiBlue ?? this.aiBlue,
      aiCyan: aiCyan ?? this.aiCyan,
      warm: warm ?? this.warm,
      health: health ?? this.health,
      heartFg: heartFg ?? this.heartFg,
      money: money ?? this.money,
      fillSubtle: fillSubtle ?? this.fillSubtle,
      fillMuted: fillMuted ?? this.fillMuted,
      trackBar: trackBar ?? this.trackBar,
      borderDashed: borderDashed ?? this.borderDashed,
      borderCheck: borderCheck ?? this.borderCheck,
      toggleOff: toggleOff ?? this.toggleOff,
      inkOnSoon: inkOnSoon ?? this.inkOnSoon,
      onDeepPrimary: onDeepPrimary ?? this.onDeepPrimary,
      onDeepSecondary: onDeepSecondary ?? this.onDeepSecondary,
      onDeepTertiary: onDeepTertiary ?? this.onDeepTertiary,
      bodyOnCard: bodyOnCard ?? this.bodyOnCard,
      bodyOnBubble: bodyOnBubble ?? this.bodyOnBubble,
      userBubbleBg: userBubbleBg ?? this.userBubbleBg,
      userBubbleText: userBubbleText ?? this.userBubbleText,
      bodyOnInsight: bodyOnInsight ?? this.bodyOnInsight,
      privacyText: privacyText ?? this.privacyText,
      onWhitePill: onWhitePill ?? this.onWhitePill,
      avatarText: avatarText ?? this.avatarText,
      tileAi: tileAi ?? this.tileAi,
      tileHealth: tileHealth ?? this.tileHealth,
      tileMoney: tileMoney ?? this.tileMoney,
      tileWarm: tileWarm ?? this.tileWarm,
      tileInfo: tileInfo ?? this.tileInfo,
      tileTravel: tileTravel ?? this.tileTravel,
      tileHeart: tileHeart ?? this.tileHeart,
      tagPreferenceBg: tagPreferenceBg ?? this.tagPreferenceBg,
      tagPreferenceFg: tagPreferenceFg ?? this.tagPreferenceFg,
      tagHabitBg: tagHabitBg ?? this.tagHabitBg,
      tagHabitFg: tagHabitFg ?? this.tagHabitFg,
      tagGoalBg: tagGoalBg ?? this.tagGoalBg,
      tagGoalFg: tagGoalFg ?? this.tagGoalFg,
      tagRelationBg: tagRelationBg ?? this.tagRelationBg,
      tagRelationFg: tagRelationFg ?? this.tagRelationFg,
      danger: danger ?? this.danger,
      dangerBg: dangerBg ?? this.dangerBg,
      dangerText: dangerText ?? this.dangerText,
    );
  }

  @override
  AppColors lerp(covariant AppColors? other, double t) {
    if (other == null) return this;
    Color m(Color a, Color b) => Color.lerp(a, b, t)!;
    return AppColors(
      canvas: m(canvas, other.canvas),
      surface: m(surface, other.surface),
      ink: m(ink, other.ink),
      ink2: m(ink2, other.ink2),
      ink3: m(ink3, other.ink3),
      line: m(line, other.line),
      aiPrimary: m(aiPrimary, other.aiPrimary),
      aiBlue: m(aiBlue, other.aiBlue),
      aiCyan: m(aiCyan, other.aiCyan),
      warm: m(warm, other.warm),
      health: m(health, other.health),
      heartFg: m(heartFg, other.heartFg),
      money: m(money, other.money),
      fillSubtle: m(fillSubtle, other.fillSubtle),
      fillMuted: m(fillMuted, other.fillMuted),
      trackBar: m(trackBar, other.trackBar),
      borderDashed: m(borderDashed, other.borderDashed),
      borderCheck: m(borderCheck, other.borderCheck),
      toggleOff: m(toggleOff, other.toggleOff),
      inkOnSoon: m(inkOnSoon, other.inkOnSoon),
      onDeepPrimary: m(onDeepPrimary, other.onDeepPrimary),
      onDeepSecondary: m(onDeepSecondary, other.onDeepSecondary),
      onDeepTertiary: m(onDeepTertiary, other.onDeepTertiary),
      bodyOnCard: m(bodyOnCard, other.bodyOnCard),
      bodyOnBubble: m(bodyOnBubble, other.bodyOnBubble),
      userBubbleBg: m(userBubbleBg, other.userBubbleBg),
      userBubbleText: m(userBubbleText, other.userBubbleText),
      bodyOnInsight: m(bodyOnInsight, other.bodyOnInsight),
      privacyText: m(privacyText, other.privacyText),
      onWhitePill: m(onWhitePill, other.onWhitePill),
      avatarText: m(avatarText, other.avatarText),
      tileAi: m(tileAi, other.tileAi),
      tileHealth: m(tileHealth, other.tileHealth),
      tileMoney: m(tileMoney, other.tileMoney),
      tileWarm: m(tileWarm, other.tileWarm),
      tileInfo: m(tileInfo, other.tileInfo),
      tileTravel: m(tileTravel, other.tileTravel),
      tileHeart: m(tileHeart, other.tileHeart),
      tagPreferenceBg: m(tagPreferenceBg, other.tagPreferenceBg),
      tagPreferenceFg: m(tagPreferenceFg, other.tagPreferenceFg),
      tagHabitBg: m(tagHabitBg, other.tagHabitBg),
      tagHabitFg: m(tagHabitFg, other.tagHabitFg),
      tagGoalBg: m(tagGoalBg, other.tagGoalBg),
      tagGoalFg: m(tagGoalFg, other.tagGoalFg),
      tagRelationBg: m(tagRelationBg, other.tagRelationBg),
      tagRelationFg: m(tagRelationFg, other.tagRelationFg),
      danger: m(danger, other.danger),
      dangerBg: m(dangerBg, other.dangerBg),
      dangerText: m(dangerText, other.dangerText),
    );
  }
}

class AppGradients extends ThemeExtension<AppGradients> {
  const AppGradients({
    required this.ai,
    required this.deepSummary,
    required this.deepPersona,
    required this.deepBrief,
    required this.barMoney,
    required this.barBlue,
    required this.barPurple,
    required this.barGreen,
    required this.spark,
    required this.dayBars,
    required this.hbar,
    required this.avatar,
    required this.insightHero,
  });

  final LinearGradient ai;
  final LinearGradient deepSummary;
  final LinearGradient deepPersona;
  final LinearGradient deepBrief;
  final LinearGradient barMoney;
  final LinearGradient barBlue;
  final LinearGradient barPurple;
  final LinearGradient barGreen;
  final LinearGradient spark;
  final LinearGradient dayBars;
  final LinearGradient hbar;
  final LinearGradient avatar;
  final LinearGradient insightHero;

  static const values = AppGradients(
    ai: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFF8B6DFF), Color(0xFF4D8DFF), Color(0xFF2BD2E8)],
      stops: [0.0, 0.55, 1.0],
    ),
    deepSummary: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFF23232E), Color(0xFF33304A), Color(0xFF3E3A63)],
      stops: [0.0, 0.6, 1.0],
    ),
    deepPersona: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFF23232E), Color(0xFF37335C), Color(0xFF4A4390)],
      stops: [0.0, 0.65, 1.0],
    ),
    deepBrief: LinearGradient(
      begin: Alignment.topCenter,
      end: Alignment.bottomCenter,
      colors: [
        Color(0xFF191826),
        Color(0xFF262445),
        Color(0xFF3B3672),
        Color(0xFF4A4390),
      ],
      stops: [0.0, 0.46, 0.78, 1.0],
    ),
    barMoney: LinearGradient(
      begin: Alignment.centerLeft,
      end: Alignment.centerRight,
      colors: [Color(0xFFEFA63C), Color(0xFFFFD08A)],
    ),
    barBlue: LinearGradient(
      begin: Alignment.centerLeft,
      end: Alignment.centerRight,
      colors: [Color(0xFF3E8BFF), Color(0xFF9CC2FF)],
    ),
    barPurple: LinearGradient(
      begin: Alignment.centerLeft,
      end: Alignment.centerRight,
      colors: [Color(0xFF7A5CFF), Color(0xFFC3B3FF)],
    ),
    barGreen: LinearGradient(
      begin: Alignment.centerLeft,
      end: Alignment.centerRight,
      colors: [Color(0xFF33BC8C), Color(0xFF9FE8CF)],
    ),
    spark: LinearGradient(
      begin: Alignment.topCenter,
      end: Alignment.bottomCenter,
      colors: [Color(0xFF33BC8C), Color(0xFF9FE8CF)],
    ),
    dayBars: LinearGradient(
      begin: Alignment.topCenter,
      end: Alignment.bottomCenter,
      colors: [Color(0xFFF4C066), Color(0xFFF8DCAB)],
    ),
    hbar: LinearGradient(
      begin: Alignment.topCenter,
      end: Alignment.bottomCenter,
      colors: [Color(0xFF6E93FF), Color(0xFFB9CCFF)],
    ),
    avatar: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFFFFD9C2), Color(0xFFFF9D76)],
    ),
    insightHero: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFFFFFFFF), Color(0xFFF4F1FF)],
    ),
  );

  @override
  AppGradients copyWith({
    LinearGradient? ai,
    LinearGradient? deepSummary,
    LinearGradient? deepPersona,
    LinearGradient? deepBrief,
    LinearGradient? barMoney,
    LinearGradient? barBlue,
    LinearGradient? barPurple,
    LinearGradient? barGreen,
    LinearGradient? spark,
    LinearGradient? dayBars,
    LinearGradient? hbar,
    LinearGradient? avatar,
    LinearGradient? insightHero,
  }) {
    return AppGradients(
      ai: ai ?? this.ai,
      deepSummary: deepSummary ?? this.deepSummary,
      deepPersona: deepPersona ?? this.deepPersona,
      deepBrief: deepBrief ?? this.deepBrief,
      barMoney: barMoney ?? this.barMoney,
      barBlue: barBlue ?? this.barBlue,
      barPurple: barPurple ?? this.barPurple,
      barGreen: barGreen ?? this.barGreen,
      spark: spark ?? this.spark,
      dayBars: dayBars ?? this.dayBars,
      hbar: hbar ?? this.hbar,
      avatar: avatar ?? this.avatar,
      insightHero: insightHero ?? this.insightHero,
    );
  }

  @override
  AppGradients lerp(covariant AppGradients? other, double t) {
    if (other == null) return this;
    LinearGradient g(LinearGradient a, LinearGradient b) =>
        LinearGradient.lerp(a, b, t)!;
    return AppGradients(
      ai: g(ai, other.ai),
      deepSummary: g(deepSummary, other.deepSummary),
      deepPersona: g(deepPersona, other.deepPersona),
      deepBrief: g(deepBrief, other.deepBrief),
      barMoney: g(barMoney, other.barMoney),
      barBlue: g(barBlue, other.barBlue),
      barPurple: g(barPurple, other.barPurple),
      barGreen: g(barGreen, other.barGreen),
      spark: g(spark, other.spark),
      dayBars: g(dayBars, other.dayBars),
      hbar: g(hbar, other.hbar),
      avatar: g(avatar, other.avatar),
      insightHero: g(insightHero, other.insightHero),
    );
  }
}

class AppRadii {
  const AppRadii._();

  static const double lg = 24;
  static const double md = 18;
  static const double sm = 12;
  static const double full = 999;
  static const double bubbleTail = 6;

  static double iconTile(double size) => (size / 3).roundToDouble();

  static const BorderRadius rLg = BorderRadius.all(Radius.circular(lg));
  static const BorderRadius rMd = BorderRadius.all(Radius.circular(md));
  static const BorderRadius rSm = BorderRadius.all(Radius.circular(sm));
}

class AppSpacing {
  const AppSpacing._();

  static const double pageH = 18;
  static const double card = 18;
  static const double cardSm = 15;
  static const double gapCard = 12;
  static const double gapGrid = 11;
  static const double gapSection = 24;

  static const double statusBarHeight = 48;
  static const double tabBarHeight = 88;
  static const EdgeInsets screenPadding =
      EdgeInsets.only(top: 60, left: pageH, right: pageH, bottom: 118);
  static const double deviceWidth = 390;
  static const double deviceHeight = 844;
}

class AppElevation {
  const AppElevation._();

  static const List<BoxShadow> card = [
    BoxShadow(
      color: Color(0x0F1B1C23),
      offset: Offset(0, 10),
      blurRadius: 30,
    ),
  ];

  static const List<BoxShadow> deep = [
    BoxShadow(
      color: Color(0x591E1C37),
      offset: Offset(0, 16),
      blurRadius: 36,
    ),
  ];

  static const List<BoxShadow> orbGlow = [
    BoxShadow(
      color: Color(0x73665AFF),
      offset: Offset(0, 10),
      blurRadius: 30,
    ),
    BoxShadow(
      color: Color(0x593F96FF),
      blurRadius: 60,
    ),
  ];

  static List<BoxShadow> orbButton(Color canvas) => [
        const BoxShadow(
          color: Color(0x73665AFF),
          offset: Offset(0, 10),
          blurRadius: 24,
        ),
        BoxShadow(color: canvas, spreadRadius: 6),
      ];
}

class AppTypography {
  const AppTypography._();

  static const List<FontFeature> tabular = [FontFeature.tabularFigures()];

  static const TextStyle amountHero = TextStyle(
    fontSize: 32,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.64,
    fontFeatures: tabular,
  );

  static const TextStyle briefTitle = TextStyle(
    fontSize: 26,
    fontWeight: FontWeight.w700,
    height: 1.35,
    fontFeatures: tabular,
  );

  static const TextStyle heroTitle = TextStyle(
    fontSize: 25,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.25,
  );

  static const TextStyle pageTitle = TextStyle(
    fontSize: 24,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.24,
  );

  static const TextStyle sectionTitle = TextStyle(
    fontSize: 16.5,
    fontWeight: FontWeight.w700,
  );

  static const TextStyle body = TextStyle(
    fontSize: 14.5,
    fontWeight: FontWeight.w500,
    height: 1.65,
  );

  static const TextStyle rowTitle = TextStyle(
    fontSize: 14,
    fontWeight: FontWeight.w600,
  );

  static const TextStyle sub = TextStyle(
    fontSize: 13,
    fontWeight: FontWeight.w400,
  );

  static const TextStyle label = TextStyle(
    fontSize: 11.5,
    fontWeight: FontWeight.w600,
    letterSpacing: 0.6,
  );

  static const TextStyle caption = TextStyle(
    fontSize: 11,
    fontWeight: FontWeight.w600,
  );

  static const TextStyle tabLabel = TextStyle(
    fontSize: 10.5,
    fontWeight: FontWeight.w600,
  );

  static TextStyle numeric(TextStyle base) =>
      base.copyWith(fontFeatures: tabular);
}

class AppMotion {
  const AppMotion._();

  static const Duration pageTransition = Duration(milliseconds: 380);
  static const Duration orbBreathe = Duration(milliseconds: 4200);
  static const Duration orbSwirl = Duration(milliseconds: 7000);
  static const Duration spin = Duration(milliseconds: 900);
  static const Duration typing = Duration(milliseconds: 1100);
  static const Duration pressScale = Duration(milliseconds: 150);

  static const Curve pageCurve = Cubic(0.22, 0.9, 0.3, 1);
}

ThemeData buildAppTheme({bool dark = false}) {
  final colors = dark ? AppColors.dark : AppColors.light;

  // 手工构造 ColorScheme，禁用 fromSeed（会推导 tonal palette，与固定 token 冲突）
  final scheme = ColorScheme(
    brightness: dark ? Brightness.dark : Brightness.light,
    primary: colors.aiPrimary,
    onPrimary: Colors.white,
    secondary: colors.aiBlue,
    onSecondary: Colors.white,
    surface: colors.surface,
    onSurface: colors.ink,
    error: const Color(0xFFD86A6A),
    onError: Colors.white,
  );

  final base = ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: colors.canvas,
    splashFactory: InkRipple.splashFactory,
  );

  return base.copyWith(
    // 关闭 M3 色渗与 tonal elevation，避免视觉变「脏」
    cardTheme: CardThemeData(
      color: colors.surface,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
      shape: const RoundedRectangleBorder(borderRadius: AppRadii.rLg),
    ),
    // 用朝夕字号阶覆盖 M3 默认 TextTheme
    textTheme: base.textTheme.copyWith(
      bodyMedium: AppTypography.body.copyWith(color: colors.ink),
      bodySmall: AppTypography.sub.copyWith(color: colors.ink2),
      titleMedium: AppTypography.sectionTitle.copyWith(color: colors.ink),
    ),
    extensions: <ThemeExtension<dynamic>>[
      colors,
      AppGradients.values,
    ],
  );
}

extension AppThemeAccess on BuildContext {
  AppColors get colors => Theme.of(this).extension<AppColors>()!;
  AppGradients get gradients => Theme.of(this).extension<AppGradients>()!;
}
