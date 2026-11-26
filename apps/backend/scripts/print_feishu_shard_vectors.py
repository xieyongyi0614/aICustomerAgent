"""打印飞书会话分片的测试向量，供 **ingress 侧自测算法一致性**（FEISHU-011 方案 C）。

方案 C 要求 ingress 与应用算出**同一个分片**，否则事件会落到错误实例并被归属校验
拒绝（503）。分片算法：

    shard = crc32(open_id.encode("utf-8")) % FEISHU_INSTANCE_COUNT

`crc32` 是标准 CRC-32（IEEE 802.3，多项式 0xEDB88320，与 Python `zlib.crc32` 一致）。

用法：

    python -m scripts.print_feishu_shard_vectors              # 默认向量
    python -m scripts.print_feishu_shard_vectors --count 4     # 指定实例数
    python -m scripts.print_feishu_shard_vectors --open-id ou_xxx

在 ingress 侧用同样的 `open_id` 与 `count` 跑一遍，**输出必须逐行一致**；不一致
说明哈希函数不同（例如 nginx `split_clients` 用的是 murmur2，**不是 crc32**），
必须改用能精确实现 CRC-32 的组件（如 OpenResty + Lua）。
"""

import argparse
import zlib

from app.channels.feishu import shards

DEFAULT_VECTORS = (
    "ou_e2e_alice",
    "ou_B_iso",
    "ou_1",
    "ou_2",
    "ou_demo_user",
    "ou_0000000000000000",
    "ou_zzzzzzzzzzzzzzzz",
    "ou_测试用户",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="飞书会话分片测试向量")
    parser.add_argument(
        "--count", type=int, default=4, help="FEISHU_INSTANCE_COUNT（默认 4）"
    )
    parser.add_argument("--open-id", action="append", default=None, help="自定义 open_id（可多次）")
    args = parser.parse_args()

    open_ids = tuple(args.open_id) if args.open_id else DEFAULT_VECTORS
    print(f"# 分片算法: {shards.SHARD_ALGORITHM}")
    print(f"# FEISHU_INSTANCE_COUNT={args.count}")
    print(f"{'open_id':<24} {'crc32':>12}  shard")
    for open_id in open_ids:
        raw = zlib.crc32(open_id.encode("utf-8"))
        print(f"{open_id:<24} {raw:>12}  {shards.shard_of(open_id, args.count)}")


if __name__ == "__main__":
    main()
