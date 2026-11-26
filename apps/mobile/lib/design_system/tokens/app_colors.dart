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
    required this.transparent,
    required this.wechat,
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

  /// 健康（心）图标前景（skill `tokens.md:69`：#F06A6A）——生活宫格「健康」格专用，
  /// 与青绿 `health`（健康域/完成态）不是同一语义，勿合并。
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
  final Color transparent;
  final Color wechat;

  /// 破坏性操作文字（退出登录等）
  final Color danger;

  /// A36 actionbar 危险项底色（skill `components.md:369`：rgba(240,106,106,.12)）
  final Color dangerBg;

  /// A36 actionbar 危险项字色（skill `components.md:369`：#E05252）
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
    transparent: Color(0x00000000),
    wechat: Color(0xFF07C160),
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
    transparent: Color(0x00000000),
    wechat: Color(0xFF07C160),
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
    Color? transparent,
    Color? wechat,
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
      transparent: transparent ?? this.transparent,
      wechat: wechat ?? this.wechat,
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
      transparent: m(transparent, other.transparent),
      wechat: m(wechat, other.wechat),
      danger: m(danger, other.danger),
      dangerBg: m(dangerBg, other.dangerBg),
      dangerText: m(dangerText, other.dangerText),
    );
  }
}
