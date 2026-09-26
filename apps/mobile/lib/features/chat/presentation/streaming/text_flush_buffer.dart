import 'dart:async';

/// 合帧节流：16ms 窗口 flush 累积文本，禁止逐 token setState。
class TextFlushBuffer {
  TextFlushBuffer({
    this.window = const Duration(milliseconds: 16),
    this.onFlush,
  });

  final Duration window;
  final void Function(String accumulated)? onFlush;

  final StringBuffer _pending = StringBuffer();
  String _flushed = '';
  Timer? _timer;
  int generation = 0;

  String get text => _flushed + _pending.toString();
  String get flushedText => _flushed;

  void add(String delta) {
    _pending.write(delta);
    _timer ??= Timer(window, _flush);
  }

  void _flush() {
    _timer = null;
    if (_pending.isEmpty) return;
    _flushed += _pending.toString();
    _pending.clear();
    generation += 1;
    onFlush?.call(_flushed);
  }

  String flushNow() {
    _timer?.cancel();
    _timer = null;
    _flush();
    return _flushed;
  }

  /// 整段替换：丢弃未 flush 的增量，以替换文本为唯一真相。
  void replaceWith(String text) {
    _timer?.cancel();
    _timer = null;
    _pending.clear();
    _flushed = text;
    generation += 1;
  }

  void dispose() {
    _timer?.cancel();
    _timer = null;
    _pending.clear();
  }
}

