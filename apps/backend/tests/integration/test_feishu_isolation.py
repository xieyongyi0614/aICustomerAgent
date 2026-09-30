"""多用户隔离回归（FEISHU-006 §6.4）：六项资源交叉断言 + 并发场景。"""

import asyncio
from datetime import datetime, timezone

import pytest

from app.channels.base import InboundMessage
from app.channels.feishu import adapter
from app.channels.feishu import client as feishu_client
from app.channels.feishu import delivery
from app.core import llm_factory
from app.models.character_state import CharacterState
from app.models.relationship import RelationshipState
from app.models.world import WorldObject
from app.repositories import (
    character_state_repository,
    conversation_repository,
    memory_repository,
    relationship_repository,
    world_repository,
)
from app.services.identity import channel as channel_identity_service

TOKEN_URL_PART = "tenant_access_token"
APP_SETTINGS = {
    "feishu_enabled": True,
    "feishu_app_id": "cli_iso",
    "feishu_app_secret": "secret-iso-value",
    "feishu_verification_token": "vtoken-iso",
}


def _structured_responses():
    return {
        "RoleMode": {"mode": "default", "intent": "casual", "confidence": 0.9, "reason": "hi"},
        "MemoryExtraction": {"candidates": []},
    }


def _inbound(text, open_id, reply_ref):
    return InboundMessage(
        channel="feishu",
        external_user_id=open_id,
        text=text,
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        reply_ref=reply_ref,
        metadata={},
    )


class IsoTransport:
    def __init__(self):
        self.reply_counts = {}

    async def post_json(self, url, body, timeout, headers=None):
        if TOKEN_URL_PART in url:
            return feishu_client.HttpResponse(
                status=200, json={"code": 0, "tenant_access_token": "t-iso", "expire": 7200}, raw_len=8
            )
        message_ref = url.rsplit("/", 2)[-2]
        self.reply_counts[message_ref] = self.reply_counts.get(message_ref, 0) + 1
        return feishu_client.HttpResponse(
            status=200,
            json={"code": 0, "msg": "ok", "data": {"message_id": f"om_{message_ref}"}},
            raw_len=8,
        )


@pytest.fixture(autouse=True)
def _reset_state(override_settings):
    override_settings(**APP_SETTINGS)
    feishu_client.reset_feishu_client()
    adapter.reset_feishu_adapter()
    yield
    feishu_client.reset_feishu_client()
    adapter.reset_feishu_adapter()


@pytest.mark.asyncio
async def test_two_users_six_resources_isolated(db_session_factory, fake_llm):
    llm_factory.set_llm(
        fake_llm(response=["好的"], structured_responses=_structured_responses())
    )
    transport = IsoTransport()
    feishu_client.set_transport(transport)

    identity_a = channel_identity_service.resolve("feishu", "ou_A_iso")
    identity_b = channel_identity_service.resolve("feishu", "ou_B_iso")
    assert identity_a.internal_user_id != identity_b.internal_user_id
    assert identity_a.session_id != identity_b.session_id

    outcome_a = await adapter.handle_inbound_message(_inbound("我是A", "ou_A_iso", "om_iso_a1"))
    outcome_b = await adapter.handle_inbound_message(_inbound("我是B", "ou_B_iso", "om_iso_b1"))
    assert outcome_a.error_kind is None, outcome_a
    assert outcome_b.error_kind is None, outcome_b

    conversation_a = conversation_repository.find_conversation("feishu:ou_A_iso")
    conversation_b = conversation_repository.find_conversation("feishu:ou_B_iso")
    assert conversation_a is not None and conversation_b is not None
    assert conversation_a.user_id == "feishu:ou_A_iso"
    assert conversation_b.user_id == "feishu:ou_B_iso"
    assert conversation_repository.count_messages("feishu:ou_A_iso") == 2
    assert conversation_repository.count_messages("feishu:ou_B_iso") == 2

    memory_repository.create_memory(
        "feishu:ou_A_iso", "asuna", "A 喜欢寿司", "user_preference", 0.8
    )
    assert memory_repository.list_by_user("feishu:ou_A_iso")
    assert memory_repository.list_by_user("feishu:ou_B_iso") == []

    world_a = world_repository.ensure_world("feishu:ou_A_iso")
    world_b = world_repository.ensure_world("feishu:ou_B_iso")
    assert world_a.world_id == "home:feishu:ou_A_iso"
    assert world_b.world_id == "home:feishu:ou_B_iso"
    assert world_a.world_id != world_b.world_id
    world_repository.save_object(
        WorldObject(
            id="obj_iso_a",
            world_id=world_a.world_id,
            name="A的煎锅",
            location_id="kitchen",
            state="idle",
        )
    )
    assert world_repository.get_object(world_a.world_id, "obj_iso_a") is not None
    assert world_repository.get_object(world_b.world_id, "obj_iso_a") is None

    relationship_repository.upsert_relationship(
        "feishu:ou_A_iso", RelationshipState(intimacy=0.9)
    )
    assert (
        relationship_repository.get_relationship("feishu:ou_A_iso").intimacy
        == pytest.approx(0.9)
    )
    assert (
        relationship_repository.get_relationship("feishu:ou_B_iso").intimacy
        == pytest.approx(0.3)
    )

    character_state_repository.upsert_state(
        "feishu:ou_A_iso", CharacterState(mood="happy")
    )
    state_b = character_state_repository.get_state("feishu:ou_B_iso")
    assert state_b.mood != "happy"

    _drain_backgrounds()


def _drain_backgrounds() -> None:
    from tests.conftest import wait_until
    from app.application import observability, post_process

    wait_until(
        lambda: not (observability.background_tasks or post_process.background_tasks),
        timeout=8.0,
    )


@pytest.mark.asyncio
async def test_two_users_concurrent_turns_no_cross_talk(db_session_factory, monkeypatch):
    order = []

    async def _stream(session_id, user_id, content, llm=None, trace=None):
        await asyncio.sleep(0.05 if user_id.endswith("A_cc") else 0.0)
        order.append((user_id, content))
        yield {"kind": "token", "text": f"reply-{content}"}
        yield {"kind": "done", "turn_id": content}

    monkeypatch.setattr(adapter.agent_service, "stream_chat", _stream)
    channel_identity_service.resolve("feishu", "ou_A_cc")
    channel_identity_service.resolve("feishu", "ou_B_cc")

    tasks = [
        adapter.handle_inbound_message(_inbound("A1", "ou_A_cc", "om_cc_a1")),
        adapter.handle_inbound_message(_inbound("B1", "ou_B_cc", "om_cc_b1")),
        adapter.handle_inbound_message(_inbound("A2", "ou_A_cc", "om_cc_a2")),
        adapter.handle_inbound_message(_inbound("B2", "ou_B_cc", "om_cc_b2")),
    ]
    outcomes = await asyncio.gather(*tasks)
    assert all(outcome.error_kind is None for outcome in outcomes)
    assert {outcome.user_id for outcome in outcomes} == {"feishu:ou_A_cc", "feishu:ou_B_cc"}
    a_texts = [content for user_id, content in order if user_id == "feishu:ou_A_cc"]
    b_texts = [content for user_id, content in order if user_id == "feishu:ou_B_cc"]
    assert a_texts == ["A1", "A2"]
    assert b_texts == ["B1", "B2"]
