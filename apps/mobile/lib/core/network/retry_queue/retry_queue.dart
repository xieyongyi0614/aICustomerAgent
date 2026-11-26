/// 写失败进重试队列的状态枚举与接口。
/// V1 不做 Offline-first 写路径，仅预留「待同步」展示能力。
enum RetryStatus { pending, syncing, failed, done }

class RetryItem {
  const RetryItem({
    required this.id,
    required this.kind,
    required this.status,
    this.payloadJson,
  });

  final String id;
  final String kind;
  final RetryStatus status;
  final String? payloadJson;
}

abstract interface class RetryQueue {
  Future<void> enqueue(RetryItem item);
  Future<List<RetryItem>> pending();
  Future<void> mark(String id, RetryStatus status);
}

class InMemoryRetryQueue implements RetryQueue {
  final _items = <String, RetryItem>{};

  @override
  Future<void> enqueue(RetryItem item) async => _items[item.id] = item;

  @override
  Future<List<RetryItem>> pending() async => _items.values
      .where((e) => e.status == RetryStatus.pending || e.status == RetryStatus.failed)
      .toList();

  @override
  Future<void> mark(String id, RetryStatus status) async {
    final cur = _items[id];
    if (cur == null) return;
    _items[id] = RetryItem(
      id: cur.id,
      kind: cur.kind,
      status: status,
      payloadJson: cur.payloadJson,
    );
  }
}
