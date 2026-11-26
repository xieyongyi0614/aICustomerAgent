"""飞书会话收件箱：连发合并 + FIFO 批次链 + 队列背压（FEISHU-007）。"""

import asyncio
from datetime import datetime, timezone

import pytest

from app.channels.base import InboundMessage
from app.channels.feishu.inbox import MERGE_SEPARATOR, SessionInbox


def _inbound(text, open_id="ou_inbox", reply_ref=None):
    return InboundMessage(
        channel="feishu",
        external_user_id=open_id,
        text=text,
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reply_ref=reply_ref or f"om_{text}",
        metadata={"seq": text},
    )


class _Recorder:
    def __init__(self, gate=None):
        self.batches: list[InboundMessage] = []
        self.gate = gate

    async def __call__(self, batch: InboundMessage) -> None:
        self.batches.append(batch)
        if self.gate is not None:
            await self.gate.wait()


@pytest.mark.asyncio
async def test_merge_window_coalesces_in_arrival_order(override_settings):
    override_settings(feishu_merge_window_ms=40, feishu_merge_max_messages=10)
    recorder = _Recorder()
    inbox = SessionInbox(recorder)

    for text in ("一", "二", "三"):
        assert inbox.offer(_inbound(text)) is True
    await asyncio.sleep(0.15)

    assert len(recorder.batches) == 1
    batch = recorder.batches[0]
    assert batch.text == MERGE_SEPARATOR.join(["一", "二", "三"])
    assert batch.reply_ref == "om_三"
    assert batch.received_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert batch.metadata == {"seq": "三"}


@pytest.mark.asyncio
async def test_merge_window_is_fixed_not_sliding(override_settings):
    """持续打字不得把 flush 无限推迟：窗口自首条起算，不因新消息重置。"""
    override_settings(feishu_merge_window_ms=60)
    recorder = _Recorder()
    inbox = SessionInbox(recorder)

    inbox.offer(_inbound("首"))
    for index in range(4):
        await asyncio.sleep(0.03)
        inbox.offer(_inbound(f"续{index}"))
    await asyncio.sleep(0.1)

    assert len(recorder.batches) >= 1
    assert recorder.batches[0].text.startswith("首")


@pytest.mark.asyncio
async def test_zero_window_flushes_each_message_in_order(override_settings):
    override_settings(feishu_merge_window_ms=0)
    recorder = _Recorder()
    inbox = SessionInbox(recorder)

    for index in range(5):
        assert inbox.offer(_inbound(f"m{index}")) is True
    await asyncio.sleep(0.05)

    assert [batch.text for batch in recorder.batches] == [f"m{i}" for i in range(5)]


@pytest.mark.asyncio
async def test_max_messages_flushes_immediately(override_settings):
    override_settings(feishu_merge_window_ms=5000, feishu_merge_max_messages=3)
    recorder = _Recorder()
    inbox = SessionInbox(recorder)

    for text in ("a", "b", "c"):
        inbox.offer(_inbound(text))
    await asyncio.sleep(0.05)

    assert len(recorder.batches) == 1
    assert recorder.batches[0].text == "a\nb\nc"


@pytest.mark.asyncio
async def test_max_chars_flushes_immediately(override_settings):
    override_settings(feishu_merge_window_ms=5000, feishu_merge_max_chars=5)
    recorder = _Recorder()
    inbox = SessionInbox(recorder)

    inbox.offer(_inbound("abc"))
    inbox.offer(_inbound("def"))
    await asyncio.sleep(0.05)

    assert len(recorder.batches) == 1


@pytest.mark.asyncio
async def test_queue_limit_rejects_and_recovers(override_settings):
    override_settings(feishu_merge_window_ms=0, feishu_session_queue_limit=1)
    gate = asyncio.Event()
    recorder = _Recorder(gate=gate)
    inbox = SessionInbox(recorder)

    assert inbox.offer(_inbound("m1")) is True
    await asyncio.sleep(0.05)
    assert inbox.offer(_inbound("m2")) is False
    assert inbox.pending("ou_inbox") == 1

    gate.set()
    await asyncio.sleep(0.05)
    assert inbox.pending("ou_inbox") == 0
    assert inbox.offer(_inbound("m3")) is True
    await asyncio.sleep(0.05)

    assert [batch.text for batch in recorder.batches] == ["m1", "m3"]


@pytest.mark.asyncio
async def test_sessions_are_isolated_by_open_id(override_settings):
    override_settings(feishu_merge_window_ms=0)
    recorder = _Recorder()
    inbox = SessionInbox(recorder)

    inbox.offer(_inbound("a", open_id="ou_a"))
    inbox.offer(_inbound("b", open_id="ou_b"))
    await asyncio.sleep(0.05)

    assert sorted(batch.external_user_id for batch in recorder.batches) == ["ou_a", "ou_b"]
    assert inbox.pending("ou_a") == 0
    assert inbox.pending("ou_b") == 0


@pytest.mark.asyncio
async def test_reset_cancels_pending_timer(override_settings):
    override_settings(feishu_merge_window_ms=40)
    recorder = _Recorder()
    inbox = SessionInbox(recorder)

    inbox.offer(_inbound("永不 flush"))
    inbox.reset()
    await asyncio.sleep(0.12)

    assert recorder.batches == []
    assert inbox.pending("ou_inbox") == 0


@pytest.mark.asyncio
async def test_handler_exception_does_not_stop_queue(override_settings):
    override_settings(feishu_merge_window_ms=0)
    seen = []

    async def _handler(batch):
        seen.append(batch.text)
        if batch.text == "boom":
            raise RuntimeError("boom")

    inbox = SessionInbox(_handler)
    for text in ("a", "boom", "b"):
        inbox.offer(_inbound(text))
    await asyncio.sleep(0.05)

    assert seen == ["a", "boom", "b"]
    assert inbox.pending("ou_inbox") == 0
