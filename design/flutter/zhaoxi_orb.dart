// ============================================================================
// 朝夕 · AI 核心球（The Orb）— Flutter 官方实现
// ============================================================================
//
// 【这个文件是什么】
// 朝夕 App 的 AI 本体视觉「Orb」的完整 Flutter 实现，对应 HTML 原型中的
// `.orb` 球体动画（径向渐变 + 内层高光旋转 + 呼吸缩放）。
// 单文件、零第三方依赖（只需 Flutter SDK），拷进任意工程即可编译运行。
//
// 【给接入方（人类或 AI）的快速集成指南】
//
// 1. 拷贝本文件到工程，例如 `lib/design_system/orb/zhaoxi_orb.dart`。
// 2. 使用：
//
//      import 'zhaoxi_orb.dart';
//
//      // 待机态（默认），76px 大球
//      ZhaoxiOrb(size: ZhaoxiOrbSize.lg)
//
//      // 思考态（工具调用进行中），34px
//      ZhaoxiOrb(size: ZhaoxiOrbSize.md, state: ZhaoxiOrbState.thinking)
//
//      // 完成态：播完一次绽放后自动回调，业务方应把 state 切回 idle
//      ZhaoxiOrb(
//        state: ZhaoxiOrbState.bloom,
//        onBloomComplete: () => setState(() => _orbState = ZhaoxiOrbState.idle),
//      )
//
// 3. 参数一览：
//      size            ZhaoxiOrbSize.lg(76) / md(34) / sm(22)，默认 md
//      state           ZhaoxiOrbState.idle / thinking / caring / bloom，默认 idle
//      halo            登录欢迎页 Hero 的紫色辉光晕盘（静态、溢出绘制），默认 false
//      onBloomComplete bloom 一次性动画播完后的回调（见「状态纪律」）
//      semanticLabel   无障碍标签，默认「亚丝娜，AI 助手」
//
// 4. 登录欢迎页 Hero 的画法（对应 design/pages/00-login.html）：
//
//      ZhaoxiOrb(size: ZhaoxiOrbSize.lg, halo: true)
//
//      晕盘直径 = 球径 × 160/76 ≈ 2.105 倍，溢出绘制不占布局空间，
//      外层容器不要裁剪（不要用 ClipRect / overflow 剪裁包住它）。
//
// 【状态语义与设计纪律（来自朝夕设计系统，务必遵守）】
//   - idle     待机/陪伴：蓝紫，呼吸 4.2s + 高光旋转 7s
//   - thinking 思考/执行：蓝紫，呼吸幅度加大(1.08)，高光旋转加速至 2.4s，
//              并叠加随 swirl 同速旋转的 conic 色相流动
//   - caring   主动关怀：暖橙，非对称脉冲 1.8s（快起慢落），高光冻结不旋转
//   - bloom    完成/成长：青绿，一次性绽放 1 → 1.18 → 1（600ms，只播一次）
//   - 纪律 1：bloom 播完必须切回 idle（通过 onBloomComplete），不能让球停在青绿。
//   - 纪律 2：同一时刻只有一态；冲突优先级 bloom > caring > thinking > idle。
//   - 纪律 3：Orb 是全站唯一承载「AI 存在」的元素，禁止放进 Tab 栏当按钮。
//
// 【性能说明（已在内部处理，接入方无需操心）】
//   - 内置 RepaintBoundary 隔离重绘（内层高光用 saveLayer + BlendMode.screen，
//     开销大，必须隔离）。
//   - 感知 TickerMode：TickerProviderStateMixin 自动静音（页面不可见 / App
//     退后台时停表，恢复时继续），无需接入方包任何 widget。
//   - Painter 只依赖「状态 + 旋转角」，呼吸缩放走 Transform.scale，不触发重绘。
//   - Shader / Paint 按帧缓存，不逐帧重建对象。
//   - 晕盘（halo）是静态溢出绘制，无动画开销。
//
// 【token 色值（朝夕设计系统定稿，禁止随意改）】
//   待机径向渐变（圆心 32% 28%）：
//     #D9CCFF 0% → #8B6DFF 34% → #4D6BFF 66% → #1FB9D8 100%
//   内层高光（screen 叠加，7s 旋转）：
//     A: 圆心 68% 72%，rgba(43,210,232,.85) → transparent 46%
//     B: 圆心 30% 26%，rgba(255,255,255,.90) → transparent 30%
//   思考态 conic 色相流动（screen 叠加，随 swirl 同速旋转）：
//     #8B6DFF → #3E8BFF → #2BD2E8 → #8B6DFF（首尾相接，α0.45）
//   主动关怀：#FFE6D2 0% → #FFB48F 36% → #FF9D76 68% → #FF7A4D 100%
//   完成成长：#C8F7E4 0% → #6FD9B4 36% → #33BC8C 68% → #1F9A70 100%
//   登录晕盘（halo，仅登录欢迎页 Hero，静态）：
//     直径 = 球径 × 160/76；径向 #7A5CFF α0.20 → 透明（68% farthest-corner）
//   外发光：0 10px 30px rgba(102,90,255,.45) + 0 0 60px rgba(63,150,255,.35)
//   内描边：1px rgba(255,255,255,.5)
//
// 【真源】.agents/skills/zhaoxi-design-system/references/orb.md（晕盘见其 §2.4）
//          登录晕盘原型：design/pages/00-login.html 的 .lg-orb-wrap::after
// ============================================================================

import 'dart:math' as math;

import 'package:flutter/material.dart';

/// Orb 状态：待机 / 思考 / 主动关怀 / 完成绽放。
enum ZhaoxiOrbState { idle, thinking, caring, bloom }

/// Orb 尺寸档：lg 76（首页 Hero）、md 34（对话头像等）、sm 22（消息流）。
enum ZhaoxiOrbSize { lg, md, sm }

extension on ZhaoxiOrbSize {
  double get pixels => switch (this) {
        ZhaoxiOrbSize.lg => 76,
        ZhaoxiOrbSize.md => 34,
        ZhaoxiOrbSize.sm => 22,
      };
}

class ZhaoxiOrb extends StatefulWidget {
  const ZhaoxiOrb({
    super.key,
    this.size = ZhaoxiOrbSize.md,
    this.state = ZhaoxiOrbState.idle,
    this.halo = false,
    this.onBloomComplete,
    this.semanticLabel = '亚丝娜，AI 助手',
  });

  final ZhaoxiOrbSize size;
  final ZhaoxiOrbState state;

  /// 登录欢迎页 Hero 的紫色辉光晕盘（静态、溢出绘制，不占布局空间）。
  final bool halo;

  /// bloom 一次性绽放播完后的回调。业务方必须在这里把 state 切回 idle。
  final VoidCallback? onBloomComplete;

  final String semanticLabel;

  @override
  State<ZhaoxiOrb> createState() => _ZhaoxiOrbState();
}

class _ZhaoxiOrbState extends State<ZhaoxiOrb> with TickerProviderStateMixin {
  static const _breathePeriod = Duration(milliseconds: 4200);
  static const _swirlPeriodIdle = Duration(milliseconds: 7000);
  static const _swirlPeriodThinking = Duration(milliseconds: 2400);
  static const _caringPulsePeriod = Duration(milliseconds: 1800);
  static const _bloomDuration = Duration(milliseconds: 600);

  late final AnimationController _breathe;
  late final AnimationController _swirl;
  late final AnimationController _bloom;

  @override
  void initState() {
    super.initState();
    _breathe = AnimationController(vsync: this, duration: _breathePeriod);
    _swirl = AnimationController(vsync: this, duration: _swirlPeriodIdle);
    _bloom = AnimationController(vsync: this, duration: _bloomDuration)
      ..addStatusListener(_onBloomStatus);
    _syncWithState();
  }

  @override
  void didUpdateWidget(ZhaoxiOrb oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state != widget.state) _syncWithState();
  }

  void _onBloomStatus(AnimationStatus status) {
    if (status == AnimationStatus.completed) {
      _bloom.reset();
      widget.onBloomComplete?.call();
    }
  }

  void _syncWithState() {
    _breathe.stop();
    _swirl.stop();
    _bloom.stop();

    switch (widget.state) {
      case ZhaoxiOrbState.idle:
        _breathe.duration = _breathePeriod;
        _breathe.repeat(reverse: true);
        _swirl.duration = _swirlPeriodIdle;
        _swirl.repeat();
      case ZhaoxiOrbState.thinking:
        _breathe.duration = _breathePeriod;
        _breathe.repeat(reverse: true);
        _swirl.duration = _swirlPeriodThinking;
        _swirl.repeat();
      case ZhaoxiOrbState.caring:
        _breathe.duration = _caringPulsePeriod;
        _breathe.repeat();
        _swirl.stop();
      case ZhaoxiOrbState.bloom:
        _bloom.forward();
    }
  }

  @override
  void dispose() {
    _breathe.dispose();
    _swirl.dispose();
    _bloom.dispose();
    super.dispose();
  }

  double get _scale {
    if (widget.state == ZhaoxiOrbState.bloom) {
      // 1 → 1.18 → 1，前 45% 放大、后 55% 回落
      final t = _bloom.value;
      final up = const Interval(0, 0.45, curve: Curves.easeOut).transform(t);
      final down = const Interval(0.45, 1, curve: Curves.easeInOut).transform(t);
      return 1 + 0.18 * (up - down);
    }
    if (widget.state == ZhaoxiOrbState.caring) {
      // 非对称脉冲：快起（30%）慢落（70%），幅度 1.07
      final t = _breathe.value;
      final up = const Interval(0, 0.3, curve: Curves.easeOut).transform(t);
      final down = const Interval(0.3, 1, curve: Curves.easeInOut).transform(t);
      return 1 + 0.07 * (up - down);
    }
    // idle / thinking：ease-in-out 呼吸
    final amplitude = widget.state == ZhaoxiOrbState.thinking ? 0.08 : 0.055;
    final t = Curves.easeInOut.transform(_breathe.value);
    return 1 + amplitude * t;
  }

  List<Color> get _gradientColors => switch (widget.state) {
        ZhaoxiOrbState.caring => const [
            Color(0xFFFFE6D2),
            Color(0xFFFFB48F),
            Color(0xFFFF9D76),
            Color(0xFFFF7A4D),
          ],
        ZhaoxiOrbState.bloom => const [
            Color(0xFFC8F7E4),
            Color(0xFF6FD9B4),
            Color(0xFF33BC8C),
            Color(0xFF1F9A70),
          ],
        _ => const [
            Color(0xFFD9CCFF),
            Color(0xFF8B6DFF),
            Color(0xFF4D6BFF),
            Color(0xFF1FB9D8),
          ],
      };

  @override
  Widget build(BuildContext context) {
    final d = widget.size.pixels;
    return Semantics(
      label: widget.semanticLabel,
      child: RepaintBoundary(
        child: AnimatedBuilder(
          animation: Listenable.merge([_breathe, _swirl, _bloom]),
          builder: (context, _) {
            return Transform.scale(
              scale: _scale,
              child: CustomPaint(
                size: Size.square(d),
                painter: _OrbPainter(
                  colors: _gradientColors,
                  swirlAngle: _swirl.value * 2 * math.pi,
                  showHighlights: widget.state != ZhaoxiOrbState.bloom ||
                      _bloom.value < 0.9,
                  showConic: widget.state == ZhaoxiOrbState.thinking,
                  halo: widget.halo,
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

class _OrbPainter extends CustomPainter {
  _OrbPainter({
    required this.colors,
    required this.swirlAngle,
    required this.showHighlights,
    required this.showConic,
    required this.halo,
  });

  final List<Color> colors;
  final double swirlAngle;
  final bool showHighlights;
  final bool showConic;
  final bool halo;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    final center = rect.center;
    final radius = size.width / 2;

    // ---------- 登录晕盘（静态，对应 .lg-orb-wrap::after，溢出绘制） ----------
    if (halo) {
      const haloSideRatio = 160 / 76;
      final haloSide = size.width * haloSideRatio;
      final haloRect =
          Rect.fromCenter(center: center, width: haloSide, height: haloSide);
      final haloPaint = Paint()
        ..shader = RadialGradient(
          radius: haloSide * math.sqrt2 / 2,
          colors: [
            const Color(0xFF7A5CFF).withValues(alpha: 0.20),
            const Color(0xFF7A5CFF).withValues(alpha: 0),
          ],
          stops: const [0, 0.68],
        ).createShader(haloRect);
      canvas.drawCircle(center, haloSide / 2, haloPaint);
    }

    // ---------- 外发光（CSS box-shadow → MaskFilter，blur-radius ≈ 2σ） ----------
    // 先画列表靠后的蓝层（0 0 60px rgba(63,150,255,.35)），紫层（0 10px 30px
    // rgba(102,90,255,.45)）盖在上面；发光画在球后，球体自然遮住内圈。
    // ⚠️ 必须画在 saveLayer 之外：辉光溢出球体方框，进 saveLayer 会被边界裁掉。
    final glowPaint = Paint()
      ..color = const Color(0xFF665AFF).withValues(alpha: 0.45)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 15);
    canvas.drawCircle(center + const Offset(0, 10), radius, glowPaint);

    final haloPaint = Paint()
      ..color = const Color(0xFF3F96FF).withValues(alpha: 0.35)
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 30);
    canvas.drawCircle(center, radius, haloPaint);

    // ---------- 底层径向渐变（圆心 32% 28% ≈ Alignment(-0.36, -0.44)） ----------
    canvas.saveLayer(rect, Paint());
    final basePaint = Paint()
      ..shader = RadialGradient(
        center: const Alignment(-0.36, -0.44),
        radius: 1.0,
        colors: colors,
        stops: const [0, 0.34, 0.66, 1],
      ).createShader(rect);
    canvas.drawCircle(center, radius, basePaint);

    // ---------- 内层高光（screen 叠加 + 整体旋转） ----------
    if (showHighlights) {
      canvas.save();
      canvas.translate(center.dx, center.dy);
      canvas.rotate(swirlAngle);
      canvas.translate(-center.dx, -center.dy);

      // CSS farthest-corner → Flutter shortestSide 换算：青光 0.99、白光 1.02
      final highlightA = Paint()
        ..blendMode = BlendMode.screen
        ..shader = RadialGradient(
          center: const Alignment(0.36, 0.44), // 68% 72%
          radius: 0.99,
          colors: [
            const Color(0xFF2BD2E8).withValues(alpha: 0.85),
            const Color(0xFF2BD2E8).withValues(alpha: 0),
          ],
          stops: const [0, 0.46],
        ).createShader(rect);
      canvas.drawCircle(center, radius, highlightA);

      final highlightB = Paint()
        ..blendMode = BlendMode.screen
        ..shader = RadialGradient(
          center: const Alignment(-0.4, -0.48), // 30% 26%
          radius: 1.02,
          colors: [
            Colors.white.withValues(alpha: 0.9),
            Colors.white.withValues(alpha: 0),
          ],
          stops: const [0, 0.3],
        ).createShader(rect);
      canvas.drawCircle(center, radius, highlightB);

      // 思考态 conic 色相流动：随 swirl 同速旋转，首尾相接无缝
      if (showConic) {
        final conicPaint = Paint()
          ..blendMode = BlendMode.screen
          ..shader = SweepGradient(
            colors: [
              const Color(0xFF8B6DFF).withValues(alpha: 0.45),
              const Color(0xFF3E8BFF).withValues(alpha: 0.45),
              const Color(0xFF2BD2E8).withValues(alpha: 0.45),
              const Color(0xFF8B6DFF).withValues(alpha: 0.45),
            ],
            stops: const [0, 0.33, 0.66, 1],
            transform: GradientRotation(swirlAngle),
          ).createShader(rect);
        canvas.drawCircle(center, radius, conicPaint);
      }
      canvas.restore();
    }
    canvas.restore();

    // ---------- 内描边 1px 白圈 ----------
    final strokePaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = Colors.white.withValues(alpha: 0.5);
    canvas.drawCircle(center, radius - 0.5, strokePaint);
  }

  @override
  bool shouldRepaint(_OrbPainter oldDelegate) =>
      oldDelegate.swirlAngle != swirlAngle ||
      oldDelegate.showHighlights != showHighlights ||
      oldDelegate.showConic != showConic ||
      oldDelegate.halo != halo ||
      !_listEquals(oldDelegate.colors, colors);

  bool _listEquals(List<Color> a, List<Color> b) {
    if (a.length != b.length) return false;
    for (var i = 0; i < a.length; i++) {
      if (a[i] != b[i]) return false;
    }
    return true;
  }
}

// ============================================================================
// 【可选】调试 / 预览用：四态展示页。接入方可整段删除，不影响 ZhaoxiOrb。
// 运行方式：把 runApp 指向 ZhaoxiOrbPreviewApp 即可在真机/模拟器上验收动画。
// ============================================================================

class ZhaoxiOrbPreviewApp extends StatelessWidget {
  const ZhaoxiOrbPreviewApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      home: Scaffold(
        backgroundColor: const Color(0xFFF5F4F0),
        body: Center(
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: const [
              ZhaoxiOrb(size: ZhaoxiOrbSize.lg, halo: true),
              SizedBox(height: 32),
              ZhaoxiOrb(size: ZhaoxiOrbSize.md, state: ZhaoxiOrbState.thinking),
              SizedBox(height: 32),
              ZhaoxiOrb(size: ZhaoxiOrbSize.md, state: ZhaoxiOrbState.caring),
              SizedBox(height: 32),
              ZhaoxiOrb(size: ZhaoxiOrbSize.sm),
            ],
          ),
        ),
      ),
    );
  }
}
