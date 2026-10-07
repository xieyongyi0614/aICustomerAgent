/// 金额展示：服务端金额一律以**整数分**（minor）下发（录入侧也是 `×100` 转分），
/// 所以展示就该按整数拆「元 + 两位小数」。
///
/// 为什么不用 `(minor / 100).toStringAsFixed(n)`：
/// - 先除再格式化把精确的整数分变成了浮点，**多此一举**；
/// - `toStringAsFixed` 会**四舍五入**，`(0)` 那次就把 ¥48.50 显示成了 ¥49，
///   账本明细几根条加起来对不上总额（2026-10-07 实机反馈）；
/// - 整数拆法在大额下依然精确（Dart int 是 64 位，浮点只有 53 位尾数）。
library;

/// `12850` → `128.50`；`5` → `0.05`；`-4850` → `-48.50`。
String formatMinor(int minor) {
  final sign = minor < 0 ? '-' : '';
  final abs = minor.abs();
  return '$sign${abs ~/ 100}.${(abs % 100).toString().padLeft(2, '0')}';
}

/// 带 `¥` 前缀的账目金额：`12850` → `¥128.50`；负数按中文习惯写 `-¥48.50`。
String formatYuan(int minor) =>
    minor < 0 ? '-¥${formatMinor(-minor)}' : '¥${formatMinor(minor)}';

/// 整元的**纯数字**（四舍五入到元）：`342050` → `3421`。调用方自己拼 `¥` / `元`。
///
/// 摘要类用整元（首页消费速览 `¥128`、生活模块卡「本月 ¥3,420」、车辆指标卡），
/// 账本明细一律走 [formatYuan] 的 2 位小数——两边别互相「修」过去。
String formatYuanWhole(int minor) => _roundToYuan(minor).toString();

int _roundToYuan(int minor) =>
    (minor.abs() + 50) ~/ 100 * (minor.isNegative ? -1 : 1);
