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

  test('parseAmountMinor 合法形态全表', () {
    expect(parseAmountMinor('12'), 1200);
    expect(parseAmountMinor('0.5'), 50);
    expect(parseAmountMinor('0.05'), 5);
    expect(parseAmountMinor('12.34'), 1234);
    expect(parseAmountMinor(' 12.3 '), 1230);
    expect(parseAmountMinor('12.'), 1200);
    expect(parseAmountMinor('12345678'), 1234567800);
  });

  test('parseAmountMinor 非法输入返回 null，绝不静默截断', () {
    expect(parseAmountMinor('12.345'), isNull);
    expect(parseAmountMinor('0.999'), isNull);
    expect(parseAmountMinor(''), isNull);
    expect(parseAmountMinor('   '), isNull);
    expect(parseAmountMinor('abc'), isNull);
    expect(parseAmountMinor('1,234'), isNull);
    expect(parseAmountMinor('-5'), isNull);
    expect(parseAmountMinor('1.2.3'), isNull);
    expect(parseAmountMinor('.'), isNull);
  });
}
