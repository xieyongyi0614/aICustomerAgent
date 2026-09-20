"""会话分片归属：算法稳定性、分布与「错误分片」留痕（FEISHU-011 方案 C）。"""

import collections
import logging

import pytest

from app.channels.feishu import shards


@pytest.fixture(autouse=True)
def _reset_shard_state():
    shards.reset_shard_state()
    yield
    shards.reset_shard_state()


def test_single_instance_always_shard_zero():
    for count in (0, 1, -3):
        assert shards.shard_of("ou_any", count) == 0


@pytest.mark.parametrize(
    "open_id,expected",
    [
        ("ou_e2e_alice", {2: 1, 3: 0, 4: 3}),
        ("ou_B_iso", {2: 0, 3: 0, 4: 2}),
        ("ou_1", {2: 1, 3: 1, 4: 3}),
    ],
)
def test_shard_values_are_frozen(open_id, expected):
    """**golden 值**：ingress 必须逐字复刻本算法，故算法一旦改动此用例必须失败。

    算法 = `crc32(open_id.encode("utf-8")) % FEISHU_INSTANCE_COUNT`。
    若这里红了，说明分片规则变了——**必须同步改 ingress 的分流配置**，否则
    同一会话会被拆到不同实例，进程内会话锁失效。
    """
    for count, shard in expected.items():
        assert shards.shard_of(open_id, count) == shard


def test_shard_is_stable_across_calls_and_processes():
    """同输入恒同输出（无随机、无进程内状态）——这是 ingress 能复刻的前提。"""
    for _ in range(50):
        assert shards.shard_of("ou_stable", 7) == shards.shard_of("ou_stable", 7)


def test_shards_are_evenly_distributed():
    counts = collections.Counter(
        shards.shard_of(f"ou_{index}", 4) for index in range(4000)
    )
    assert sorted(counts) == [0, 1, 2, 3]
    assert all(count == 1000 for count in counts.values())


DOCUMENTED_VECTORS: dict[int, dict[str, int]] = {
    2: {
        "ou_e2e_alice": 1,
        "ou_B_iso": 0,
        "ou_1": 1,
        "ou_2": 1,
        "ou_demo_user": 0,
        "ou_0000000000000000": 1,
        "ou_zzzzzzzzzzzzzzzz": 1,
        "ou_测试用户": 0,
    },
    4: {
        "ou_e2e_alice": 3,
        "ou_B_iso": 2,
        "ou_1": 3,
        "ou_2": 1,
        "ou_demo_user": 0,
        "ou_0000000000000000": 3,
        "ou_zzzzzzzzzzzzzzzz": 1,
        "ou_测试用户": 0,
    },
}


@pytest.mark.parametrize("count", [2, 4])
def test_documented_vectors_match_implementation(count):
    """文档 `ingress-routing-options.md` §1.4 的向量表必须与实现一致。

    运维会照着这张表在 ingress 侧比对一致性；**表错了会让人误判「算法一致」**，
    从而放过真正的分片漂移。故把它钉成用例。
    """
    from scripts import print_feishu_shard_vectors as vectors

    expected = DOCUMENTED_VECTORS[count]
    for open_id, shard in expected.items():
        assert shards.shard_of(open_id, count) == shard, f"{open_id} @ n={count}"
    assert set(vectors.DEFAULT_VECTORS) == set(expected)


def test_owns_matches_shard_of():
    for index in range(4):
        for candidate in range(4):
            open_id = f"ou_owns_{candidate}"
            assert shards.owns(
                open_id, instance_index=index, instance_count=4
            ) == (shards.shard_of(open_id, 4) == index)


def test_owns_single_instance_true_for_everyone():
    assert shards.owns("ou_x", instance_index=0, instance_count=1) is True


def test_wrong_shard_is_sampled_not_flooding(caplog):
    with caplog.at_level(logging.ERROR, logger="app.channels.feishu.shards"):
        for _ in range(shards.WRONG_SHARD_SAMPLE_EVERY):
            shards.note_wrong_shard("ou_wrong", instance_index=0, instance_count=4)
    records = [r for r in caplog.records if "wrong shard" in r.getMessage()]
    assert len(records) == 1
    assert "ou_wrong" in records[0].getMessage()
    assert shards.SHARD_ALGORITHM in records[0].getMessage()


def test_wrong_shard_resumes_sampling_after_reset(caplog):
    with caplog.at_level(logging.ERROR, logger="app.channels.feishu.shards"):
        shards.note_wrong_shard("ou_w", instance_index=0, instance_count=2)
        shards.reset_shard_state()
        shards.note_wrong_shard("ou_w", instance_index=0, instance_count=2)
    assert len([r for r in caplog.records if "wrong shard" in r.getMessage()]) == 2
