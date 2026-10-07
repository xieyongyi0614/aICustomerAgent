import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/format/money.dart';

void main() {
  test('formatMinor 按整数分拆，不走浮点', () {
    expect(formatMinor(12850), '128.50');
    expect(formatMinor(4850), '48.50');
    expect(formatMinor(0), '0.00');
    expect(formatMinor(5), '0.05');
    expect(formatMinor(50), '0.50');
    expect(formatMinor(100), '1.00');
    expect(formatMinor(-12850), '-128.50');
    expect(formatMinor(-5), '-0.05');
  });

  test('formatMinor 在大额下依然精确（浮点只有 53 位尾数）', () {
    expect(formatMinor(1234567890123), '12345678901.23');
    expect(formatMinor(9007199254740993), '90071992547409.93');
  });

  test('formatYuan 带 ¥ 前缀，负数按中文习惯', () {
    expect(formatYuan(12850), '¥128.50');
    expect(formatYuan(0), '¥0.00');
    expect(formatYuan(-4850), '-¥48.50');
  });

  test('formatYuanWhole 整元摘要，四舍五入且不带 ¥', () {
    expect(formatYuanWhole(342050), '3421');
    expect(formatYuanWhole(342049), '3420');
    expect(formatYuanWhole(342000), '3420');
    expect(formatYuanWhole(0), '0');
    expect(formatYuanWhole(-342050), '-3421');
  });
}
