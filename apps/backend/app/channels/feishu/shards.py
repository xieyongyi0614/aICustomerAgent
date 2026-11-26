"""飞书入站的会话分片归属（FEISHU-011 方案 C）。

方案 C 不做分布式锁，而是让**入口按 `open_id` 把同一会话的事件恒定送到同一实例**，
于是通道层的进程内 `asyncio.Lock` 就足以保证同会话串行。

本模块是这条契约的**应用侧一半**：给出分片算法与归属判定。另一半是 ingress
（负载均衡 / 轻量 router / 分区队列），它必须用**同一个算法**分流——故算法选
标准库 `zlib.crc32`，取值稳定且各语言（nginx / Go / Node / Java）都有等价实现。

算法（必须逐字一致地复刻到 ingress）：

    shard = crc32(open_id.encode("utf-8")) % FEISHU_INSTANCE_COUNT

注意：`open_id` 是**飞书用户 open_id**，不是 `internal_user_id`，也不是 `session_id`
（后者形如 `feishu:{open_id}`，对字符串做哈希会得到不同结果）。
"""

import logging
import zlib

logger = logging.getLogger(__name__)

SHARD_ALGORITHM = 'crc32(open_id) % FEISHU_INSTANCE_COUNT'

WRONG_SHARD_SAMPLE_EVERY = 100

_wrong_shard_ops = 0


def reset_shard_state() -> None:
    global _wrong_shard_ops
    _wrong_shard_ops = 0


def shard_of(open_id: str, instance_count: int) -> int:
    """`open_id` 归属的分片下标；`instance_count <= 1` 时恒为 0（单实例不分片）。"""
    if instance_count <= 1:
        return 0
    return zlib.crc32(open_id.encode("utf-8")) % instance_count


def owns(open_id: str, *, instance_index: int, instance_count: int) -> bool:
    """本实例是否负责该 `open_id`。"""
    return shard_of(open_id, instance_count) == instance_index


def note_wrong_shard(open_id: str, *, instance_index: int, instance_count: int) -> None:
    """记录一次「事件落到了错误分片」。

    这是**契约被违反**的信号：ingress 没按算法分流。抽样记 error（避免刷爆日志），
    便于运维在翻开关后第一时间发现路由没生效。
    """
    global _wrong_shard_ops
    _wrong_shard_ops += 1
    if _wrong_shard_ops % WRONG_SHARD_SAMPLE_EVERY != 1:
        return
    logger.error(
        "feishu event landed on wrong shard: open_id=%s expected_shard=%d "
        "instance_index=%d instance_count=%d sampled_at=%d —— 检查 ingress 是否按 "
        "`%s` 分流（见 docs/integrations/feishu/multi-instance-options.md 方案 C）",
        open_id,
        shard_of(open_id, instance_count),
        instance_index,
        instance_count,
        _wrong_shard_ops,
        SHARD_ALGORITHM,
    )
