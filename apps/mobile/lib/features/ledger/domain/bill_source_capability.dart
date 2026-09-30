/// 账单来源能力**静态声明**（决策 D14 / 缺口 19）。
///
/// 微信、支付宝没有公开账单接口；Android 读短信受商店政策严格限制、iOS 无此能力。
/// 因此这里**只声明能力边界**，不含任何同步计数、同步时刻或开关（无同步能力时开关无对象）。
/// 真实账单的文件导入列 V2。
class BillSourceCapability {
  const BillSourceCapability({
    required this.title,
    required this.state,
    required this.reason,
    this.available = false,
  });

  final String title;
  final String state;
  final String reason;
  final bool available;
}

const billSourceCapabilities = <BillSourceCapability>[
  BillSourceCapability(
    title: '微信账单',
    state: '未接入',
    reason: '微信没有公开的账单接口，我读不到你的微信账单',
  ),
  BillSourceCapability(
    title: '支付宝账单',
    state: '未接入',
    reason: '支付宝没有公开的账单接口，我读不到你的支付宝账单',
  ),
  BillSourceCapability(
    title: '银行卡短信',
    state: '未接入',
    reason: '系统对短信读取限制很严，iOS 上完全不可用',
  ),
  BillSourceCapability(
    title: '语音记账',
    state: '一直开着',
    reason: '你主动说一句「午饭 35」，我就记下来',
    available: true,
  ),
];
