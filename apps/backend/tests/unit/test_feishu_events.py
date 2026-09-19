import base64
import hashlib
import json
import logging
import threading

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.channels.feishu import client as feishu_client
from app.channels.feishu import events
from app.channels.feishu.errors import FeishuAuthError, FeishuConfigError

ENCRYPT_KEY = "feishu-test-encrypt-key"
FIXED_IV = bytes(range(16))
FIXED_CIPHERTEXT = (
    "AAECAwQFBgcICQoLDA0ODzgqqmea2Rblim9WQN1V6kjBHITjbfrJLXwcDjLdUHp/+bF4lRTNxqW6TW6U7ieg03"
    "0Db9JMiN1YKhQMMIzaHpasP+O5zFNoG1ba9dC8zBPp/QCius2P8mXO5k++xpp6U9dee8oVs9kKtvRPuIvEXSCQ"
    "VK1BwHtrs4j82jkP5N5bP/kxMbZ6Q5VW2L5+46YgyhGaExkYTvLuJfYEwcpSy8OkYwKb+3QllMZws8McQ8AA2+"
    "87I22mTkl7wq703JA/3q6InbJ01IoTokl2sc0mzYPGyTCayi5Nn/dAyh7+HIZKkrjVhWrC/PR5CPG+jXkTEipM"
    "OEo9LceBP8kwbji6CF9G5k8qLpfM+FXX5R/sW0ormQFpaPONg3D8Xw0q0NEpqwUK2saLM6D95hGUhKeKCM2QY4"
    "VKLvxa92q3ZaX0mab56ZmU8vFcRsT8p7Bz/vdJ7GibtXEbn/Ofcv74p0RVfKw67AP4yktIz30AuBi63l3FKmwh"
    "kzhkPm5KVGEE+ALMllS7KyY9hUyft1pGgV3Rs1hfntmAtS6+lIMfrh81S/go"
)

VERIFICATION_TOKEN = "vtoken-unit-123"


@pytest.fixture(autouse=True)
def _reenable_app_loggers():
    """防御 `logging.config.fileConfig(disable_existing_loggers=True)` 的跨用例副作用。

    套件内存在进程内执行 alembic 迁移的用例（其 env.py 调用 fileConfig），会把
    已存在的 app.* logger 置为 disabled，导致其后所有日志断言用例捕获为空。
    本夹具在每个用例前重新启用 app.* logger，使断言与用例顺序无关。
    """
    for name, logger in list(logging.Logger.manager.loggerDict.items()):
        if (name == "app" or name.startswith("app.")) and isinstance(logger, logging.Logger):
            logger.disabled = False
    yield


@pytest.fixture(autouse=True)
def _reset_state():
    events.reset_event_state()
    yield
    events.reset_event_state()


def encrypt_payload(key: str, payload: dict, iv: bytes = FIXED_IV) -> str:
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pad = 16 - len(plain) % 16
    encryptor = Cipher(
        algorithms.AES(hashlib.sha256(key.encode("utf-8")).digest()), modes.CBC(iv)
    ).encryptor()
    return base64.b64encode(iv + encryptor.update(plain + bytes([pad]) * pad) + encryptor.finalize()).decode()


def message_event(
    event_id="evt-1",
    chat_type="p2p",
    message_type="text",
    text="你好",
    open_id="ou_alice",
    with_header=True,
):
    payload = {
        "event": {
            "sender": {"sender_id": {"open_id": open_id, "union_id": "un_x", "user_id": "uid_x"}},
            "message": {
                "message_id": "om_1",
                "chat_id": "oc_1",
                "chat_type": chat_type,
                "message_type": message_type,
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
        }
    }
    if with_header:
        payload["header"] = {
            "event_id": event_id,
            "event_type": "im.message.receive_v1",
            "create_time": "1767196800000",
            "tenant_key": "tk_a",
            "app_id": "cli_a",
            "token": VERIFICATION_TOKEN,
        }
    return payload


def sign(timestamp, nonce, key, body: bytes) -> str:
    return events.calculate_signature(timestamp, nonce, key, body)


def test_official_document_vector_decrypts_to_hello_world():
    plain = events.decrypt_bytes("test key", "P37w+VZImNgPEO1RBhJ6RtKl7n6zymIbEG1pReEzghk=")
    assert plain == b"hello world"


def test_fixed_vector_roundtrip():
    payload = events.decrypt(ENCRYPT_KEY, FIXED_CIPHERTEXT)
    assert payload["header"]["event_id"] == "evt_fixed_vector_001"
    assert payload["event"]["message"]["message_id"] == "om_fixed_001"
    parsed = events.parse_message_event(payload)
    assert parsed is not None
    assert parsed.text == "你好，亚丝娜"
    assert parsed.open_id == "ou_fixed_user"


def test_decrypt_wrong_key_raises():
    with pytest.raises(FeishuConfigError):
        events.decrypt("wrong-key", FIXED_CIPHERTEXT)


@pytest.mark.parametrize(
    "ciphertext",
    [
        "!!!not-base64!!!",
        "AAAA",
        base64.b64encode(bytes(16)).decode(),
        base64.b64encode(bytes(15) + bytes([16])).decode(),
    ],
)
def test_decrypt_corrupted_ciphertext_raises(ciphertext):
    with pytest.raises(FeishuConfigError):
        events.decrypt(ENCRYPT_KEY, ciphertext)


def test_decrypt_flipped_byte_raises():
    raw = bytearray(base64.b64decode(FIXED_CIPHERTEXT))
    raw[-1] ^= 0xFF
    with pytest.raises(FeishuConfigError):
        events.decrypt(ENCRYPT_KEY, base64.b64encode(bytes(raw)).decode())


def test_decrypt_empty_key_raises():
    with pytest.raises(FeishuConfigError):
        events.decrypt("", FIXED_CIPHERTEXT)


def test_decrypt_non_json_plaintext_raises():
    pad = 16 - len(b"hello world") % 16
    encryptor = Cipher(
        algorithms.AES(hashlib.sha256(ENCRYPT_KEY.encode()).digest()), modes.CBC(FIXED_IV)
    ).encryptor()
    raw_b64 = base64.b64encode(
        FIXED_IV + encryptor.update(b"hello world" + bytes([pad]) * pad) + encryptor.finalize()
    ).decode()
    with pytest.raises(FeishuConfigError):
        events.decrypt(ENCRYPT_KEY, raw_b64)


def test_verify_token():
    events.verify_token(VERIFICATION_TOKEN, VERIFICATION_TOKEN)
    with pytest.raises(FeishuAuthError):
        events.verify_token("wrong", VERIFICATION_TOKEN)
    with pytest.raises(FeishuAuthError):
        events.verify_token(None, VERIFICATION_TOKEN)


def test_signature_match_passes():
    body = b'{"encrypt":"x"}'
    timestamp = str(int(events._now()))
    signature = sign(timestamp, "nonce-1", ENCRYPT_KEY, body)
    events.verify_signature(body, timestamp, "nonce-1", ENCRYPT_KEY, signature)


def test_signature_mismatch_raises():
    body = b'{"encrypt":"x"}'
    timestamp = str(int(events._now()))
    with pytest.raises(FeishuAuthError):
        events.verify_signature(body, timestamp, "nonce-1", ENCRYPT_KEY, "deadbeef")


def test_signature_based_on_raw_body():
    timestamp = str(int(events._now()))
    raw = b'{"encrypt":"aaa"}'
    signature = sign(timestamp, "n", ENCRYPT_KEY, raw)
    events.verify_signature(raw, timestamp, "n", ENCRYPT_KEY, signature)
    tampered = b'{"encrypt":"bbb"}'
    with pytest.raises(FeishuAuthError):
        events.verify_signature(tampered, timestamp, "n", ENCRYPT_KEY, signature)


def test_signature_skipped_without_key_and_header(caplog):
    with caplog.at_level(logging.WARNING, logger="app.channels.feishu.events"):
        events.verify_signature(b"{}", "123", "n", "", None)
    assert any("安全性降级" in r.getMessage() for r in caplog.records)


def test_signature_with_key_but_missing_header_raises():
    with pytest.raises(FeishuAuthError):
        events.verify_signature(b"{}", "123", "n", ENCRYPT_KEY, None)


@pytest.mark.parametrize("timestamp", [None, "", "abc", "12.5"])
def test_signature_invalid_timestamp_raises(timestamp):
    with pytest.raises(FeishuAuthError):
        events.verify_signature(b"{}", timestamp, "n", ENCRYPT_KEY, "deadbeef")


def test_signature_timestamp_window_boundaries():
    events._now = lambda: 1_000_000.0
    body = b"{}"
    window = 300
    edge = "999700"
    events.verify_signature(body, edge, "n", ENCRYPT_KEY, sign(edge, "n", ENCRYPT_KEY, body))
    beyond = "999699"
    with pytest.raises(FeishuAuthError):
        events.verify_signature(body, beyond, "n", ENCRYPT_KEY, sign(beyond, "n", ENCRYPT_KEY, body))
    future_beyond = "1000301"
    with pytest.raises(FeishuAuthError):
        events.verify_signature(
            body, future_beyond, "n", ENCRYPT_KEY, sign(future_beyond, "n", ENCRYPT_KEY, body)
        )


def test_challenge_detection_and_extraction():
    assert events.is_challenge({"type": "url_verification", "challenge": "abc/+=?"})
    assert not events.is_challenge({"type": "event_callback"})
    assert events.challenge_of({"challenge": "abc/+=?"}) == "abc/+=?"
    assert events.challenge_of({"challenge": ""}) is None
    assert events.challenge_of({}) is None
    assert events.challenge_of({"challenge": 123}) is None


def test_parse_valid_event_full_fields():
    parsed = events.parse_message_event(message_event())
    assert parsed is not None
    assert parsed.event_id == "evt-1"
    assert parsed.message_id == "om_1"
    assert parsed.chat_id == "oc_1"
    assert parsed.chat_type == "p2p"
    assert parsed.message_type == "text"
    assert parsed.text == "你好"
    assert parsed.open_id == "ou_alice"
    assert parsed.tenant_key == "tk_a"
    assert parsed.union_id == "un_x"
    assert parsed.user_id == "uid_x"
    assert parsed.create_time_ms == "1767196800000"


def test_content_double_decoding_and_strip():
    payload = message_event(text="  前后空白  ")
    parsed = events.parse_message_event(payload)
    assert parsed is not None
    assert parsed.text == "前后空白"


def test_whitespace_only_text_ignored():
    assert events.parse_message_event(message_event(text="   ")) is None


def test_group_message_ignored():
    assert events.parse_message_event(message_event(chat_type="group")) is None


@pytest.mark.parametrize("message_type", ["image", "file", "audio", "post"])
def test_non_text_message_ignored(message_type):
    assert events.parse_message_event(message_event(message_type=message_type)) is None


def test_other_event_type_ignored():
    payload = message_event()
    payload["header"]["event_type"] = "contact.user.created_v3"
    assert events.parse_message_event(payload) is None


def test_missing_open_id_ignored():
    payload = message_event()
    del payload["event"]["sender"]["sender_id"]["open_id"]
    assert events.parse_message_event(payload) is None


def test_missing_event_id_ignored():
    payload = message_event()
    del payload["header"]["event_id"]
    assert events.parse_message_event(payload) is None


def test_missing_header_ignored():
    payload = message_event()
    payload["header"] = {"event_type": "im.message.receive_v1"}
    assert events.parse_message_event(payload) is None


def test_invalid_content_json_ignored():
    payload = message_event()
    payload["event"]["message"]["content"] = "not-json"
    assert events.parse_message_event(payload) is None


def test_content_missing_text_ignored():
    payload = message_event()
    payload["event"]["message"]["content"] = '{"other": 1}'
    assert events.parse_message_event(payload) is None


def test_unknown_fields_tolerated():
    payload = message_event()
    payload["header"]["unknown_field"] = "x"
    payload["event"]["extra"] = {"a": 1}
    assert events.parse_message_event(payload) is not None


def test_to_inbound_message_mapping():
    parsed = events.parse_message_event(message_event())
    inbound = events.to_inbound_message(parsed)
    assert inbound.channel == "feishu"
    assert inbound.external_user_id == "ou_alice"
    assert inbound.reply_ref == "om_1"
    assert inbound.external_thread_id == "oc_1"
    assert inbound.text == "你好"
    assert inbound.received_at.isoformat().startswith("2026-01-01") or inbound.received_at.year >= 2025
    assert inbound.metadata["tenant_key"] == "tk_a"
    assert inbound.metadata["union_id"] == "un_x"
    assert inbound.metadata["user_id"] == "uid_x"
    assert inbound.metadata["chat_type"] == "p2p"
    assert inbound.metadata["message_type"] == "text"


def test_create_time_parsed_to_utc():
    payload = message_event()
    inbound = events.to_inbound_message(events.parse_message_event(payload))
    assert inbound.received_at.tzinfo is not None
    assert int(inbound.received_at.timestamp() * 1000) == 1767196800000


def test_create_time_invalid_falls_back_to_now():
    payload = message_event()
    payload["header"]["create_time"] = "garbage"
    inbound = events.to_inbound_message(events.parse_message_event(payload))
    assert inbound.received_at.tzinfo is not None


def test_accept_event_first_true_then_false():
    assert events.accept_event("evt-dup") is True
    assert events.accept_event("evt-dup") is False
    assert events.accept_event("evt-other") is True


def test_accept_event_ttl_expiry_with_injected_clock():
    virtual = {"now": 1000.0}
    events._now = lambda: virtual["now"]
    assert events.accept_event("evt-ttl") is True
    virtual["now"] += 601
    assert events.accept_event("evt-ttl") is True


def test_accept_event_within_ttl_not_expired():
    virtual = {"now": 1000.0}
    events._now = lambda: virtual["now"]
    assert events.accept_event("evt-ttl2") is True
    virtual["now"] += 599
    assert events.accept_event("evt-ttl2") is False


def test_accept_event_concurrent_exactly_one_true():
    results = []
    barrier = threading.Barrier(8)

    def _worker():
        barrier.wait()
        results.append(events.accept_event("evt-concurrent"))

    threads = [threading.Thread(target=_worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1
    assert results.count(False) == 7


def test_allow_rate_limit_and_window(monkeypatch):
    monkeypatch.setenv("CHAT_RATE_LIMIT_PER_MINUTE", "2")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    try:
        virtual = {"now": 2000.0}
        events._now = lambda: virtual["now"]
        assert events.allow_rate("ou_r") is True
        assert events.allow_rate("ou_r") is True
        assert events.allow_rate("ou_r") is False
        assert events.allow_rate("ou_other") is True
        virtual["now"] += 61
        assert events.allow_rate("ou_r") is True
    finally:
        get_settings.cache_clear()


def test_reset_event_state_clears_everything():
    events.accept_event("evt-reset")
    events.allow_rate("ou_reset")
    events.reset_event_state()
    assert events._seen_events == {}
    assert events._rate_windows == {}
    import time as time_module

    assert events._now is time_module.time


def test_zero_real_network_during_event_processing():
    payload = events.decrypt(ENCRYPT_KEY, FIXED_CIPHERTEXT)
    events.parse_message_event(payload)
    events.accept_event("evt-net")
    events.allow_rate("ou_net")
    assert feishu_client._transport is None


def test_timestamp_freshness_window_boundaries():
    events._now = lambda: 1_000_000.0
    events.verify_timestamp_freshness("999700")
    with pytest.raises(FeishuAuthError):
        events.verify_timestamp_freshness("999699")
    with pytest.raises(FeishuAuthError):
        events.verify_timestamp_freshness("1000301")


@pytest.mark.parametrize("timestamp", [None, "", "abc", "12.5"])
def test_timestamp_freshness_rejects_invalid(timestamp):
    with pytest.raises(FeishuAuthError):
        events.verify_timestamp_freshness(timestamp)


def test_event_freshness_reads_create_time_in_milliseconds():
    events._now = lambda: 1_767_196_800.0
    payload = message_event()
    payload["header"]["create_time"] = "1767196800000"
    assert events.verify_event_freshness(payload) is True


def test_event_freshness_rejects_stale_create_time():
    events._now = lambda: 1_767_196_800.0 + 3600
    payload = message_event()
    payload["header"]["create_time"] = "1767196800000"
    with pytest.raises(FeishuAuthError):
        events.verify_event_freshness(payload)


def test_event_freshness_without_signal_returns_false():
    assert events.verify_event_freshness({}) is False
    assert events.verify_event_freshness({"header": {"create_time": "not-a-number"}}) is False


def test_encrypted_freshness_prefers_header_timestamp():
    events._now = lambda: 1_000_000.0
    events.verify_encrypted_freshness("999700", {"header": {"create_time": "1"}})
    with pytest.raises(FeishuAuthError):
        events.verify_encrypted_freshness("999699", {"header": {"create_time": "1000000000000"}})


def test_encrypted_freshness_falls_back_to_create_time():
    """无请求头时间戳时用事件 create_time 拦重放——这正是 F-01 的修复点。"""
    events._now = lambda: 1_767_196_800.0 + 3600
    payload = message_event()
    payload["header"]["create_time"] = "1767196800000"
    with pytest.raises(FeishuAuthError):
        events.verify_encrypted_freshness(None, payload)


def test_encrypted_freshness_unverifiable_is_allowed_with_warning(caplog):
    """URL 校验来件既无时间戳头也无 create_time，不得被误杀。"""
    with caplog.at_level(logging.WARNING, logger="app.channels.feishu.events"):
        events.verify_encrypted_freshness(
            None, {"type": "url_verification", "challenge": "c-1"}
        )
    assert any("freshness unverifiable" in record.getMessage() for record in caplog.records)


def test_seen_events_table_stays_bounded_after_ttl():
    """去重表按插入序批量摘除，规模不随历史事件数线性增长（F-08）。"""
    base = 1_000_000.0
    events._now = lambda: base
    for index in range(500):
        assert events.accept_event(f"evt-{index}") is True
    assert len(events._seen_events) == 500

    events._now = lambda: base + 601
    assert events.accept_event("evt-new") is True
    assert len(events._seen_events) == 1


def test_rate_windows_reclaim_stale_keys(override_settings):
    """限流表已过窗的 open_id 条目会被摊还清理，key 不永久驻留（F-08）。"""
    override_settings(chat_rate_limit_per_minute=5)
    base = 1_000_000.0
    events._now = lambda: base
    for index in range(events.RATE_SWEEP_EVERY):
        assert events.allow_rate(f"ou-{index}") is True
    assert len(events._rate_windows) == events.RATE_SWEEP_EVERY

    events._now = lambda: base + 61
    for index in range(events.RATE_SWEEP_EVERY):
        assert events.allow_rate(f"ou-new-{index}") is True

    assert set(events._rate_windows) == {
        f"ou-new-{index}" for index in range(events.RATE_SWEEP_EVERY)
    }


def test_dedupe_then_rate_does_not_consume_quota(override_settings):
    """重复事件先被去重拦下，不得消耗该用户的限流配额（F-03 的纯函数侧）。"""
    override_settings(chat_rate_limit_per_minute=1)
    assert events.accept_event("evt-dup-quota") is True
    assert events.allow_rate("ou_quota") is True
    assert events.accept_event("evt-dup-quota") is False
    assert events.allow_rate("ou_quota") is False
