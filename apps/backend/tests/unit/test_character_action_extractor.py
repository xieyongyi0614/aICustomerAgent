"""ACTION-002 AI Reply Action Extractor 单测。"""

import pytest

from app.models.character_action import TurnRef, WorldActionStatus
from app.services.character_action.extractor import (
    _is_noise,
    _parse_chinese_quantity,
    _parse_quantity,
    extract_actions,
)


def _tr(session_id: str = "s1", turn_id: str = "t1", ordinal: int = 0) -> TurnRef:
    return TurnRef(session_id=session_id, turn_id=turn_id, ordinal=ordinal)


KNOWN_NAMES = {"鸡蛋", "牛奶", "可乐", "面条", "大米", "面包", "面"}


class TestNoiseGuard:
    def test_question_mark(self):
        assert _is_noise("你想吃面吗？")

    def test_question_ne(self):
        assert _is_noise("鸡蛋还有呢")

    def test_hypothetical(self):
        assert _is_noise("如果饿了我可以做面")

    def test_future_intention(self):
        assert _is_noise("待会我给你做鸡蛋卷")

    def test_roleplay(self):
        assert _is_noise("假装我在做饭")

    def test_negative(self):
        assert _is_noise("不用了谢谢")

    def test_clean_sentence_not_noise(self):
        assert not _is_noise("我用了两个鸡蛋")

    def test_clean_create_not_noise(self):
        assert not _is_noise("我做好了一碗面")


class TestQuantityParsing:
    def test_chinese_two(self):
        assert _parse_chinese_quantity("用了两个鸡蛋") == 2.0

    def test_chinese_half(self):
        assert _parse_chinese_quantity("用了半个鸡蛋") == 0.5

    def test_chinese_one(self):
        assert _parse_chinese_quantity("拿了一个") == 1.0

    def test_arabic_number(self):
        assert _parse_quantity("用了2个鸡蛋") == 2.0

    def test_arabic_decimal(self):
        assert _parse_quantity("用了1.5斤米") == 1.5

    def test_no_number_returns_none(self):
        assert _parse_quantity("用了些鸡蛋") is None


class TestExtractConsume:
    def test_basic_consume(self):
        result = extract_actions(
            "我用了两个鸡蛋。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 1
        action = result.candidates[0]
        assert action.action_type == "CONSUME"
        assert action.target.name == "鸡蛋"
        assert action.quantity == 2.0
        assert action.status == WorldActionStatus.CANDIDATE

    def test_consume_default_quantity(self):
        result = extract_actions(
            "我用了鸡蛋。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].quantity == 1.0

    def test_consume_milk(self):
        result = extract_actions(
            "我喝了一杯牛奶。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].action_type == "CONSUME"
        assert result.candidates[0].target.name == "牛奶"

    def test_consume_multiple_items(self):
        result = extract_actions(
            "我用了两个鸡蛋，喝了一杯牛奶。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 2
        types = {c.action_type for c in result.candidates}
        assert types == {"CONSUME"}

    def test_consume_unknown_object_not_extracted(self):
        result = extract_actions(
            "我用了番茄酱。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 0


class TestExtractCreate:
    def test_basic_create(self):
        result = extract_actions(
            "我做好了一碗面。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 1
        action = result.candidates[0]
        assert action.action_type == "CREATE"
        assert action.target.name is not None
        assert action.quantity is not None

    def test_create_narrative_noun_rejected(self):
        result = extract_actions(
            "我做了个梦。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 0

    def test_create_decision_rejected(self):
        result = extract_actions(
            "我做了个决定。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 0


class TestExtractMove:
    def test_basic_move(self):
        result = extract_actions(
            "我把牛奶放到了厨房。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 1
        action = result.candidates[0]
        assert action.action_type == "MOVE"
        assert action.target.name == "牛奶"
        assert action.target.location_id == "home.kitchen"

    def test_move_to_fridge(self):
        result = extract_actions(
            "我把鸡蛋放进了冰箱。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].target.location_id == "home.kitchen.fridge"

    def test_move_nadao_table(self):
        result = extract_actions(
            "我把牛奶拿到桌上。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].action_type == "MOVE"
        assert result.candidates[0].target.name == "牛奶"
        assert result.candidates[0].target.location_id == "home.dining_area"

    def test_take_with_quantity_is_consume(self):
        result = extract_actions(
            "我拿了两个鸡蛋。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].action_type == "CONSUME"
        assert result.candidates[0].target.name == "鸡蛋"
        assert result.candidates[0].quantity == 2.0

    def test_take_qty_last_is_consume(self):
        result = extract_actions(
            "我拿出鸡蛋6个。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].action_type == "CONSUME"
        assert result.candidates[0].quantity == 6.0

    def test_take_without_quantity_is_not_consume(self):
        result = extract_actions(
            "我把牛奶拿出来看看。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 0

    def test_take_omitted_subject_resolved_from_context(self):
        result = extract_actions(
            "刚才拿了两个出来煎给你了。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
            context_text="用户：冰箱里还有几个蛋啊",
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].action_type == "CONSUME"
        assert result.candidates[0].target.name == "鸡蛋"
        assert result.candidates[0].quantity == 2.0

    def test_take_omitted_subject_without_context_stays_unresolved(self):
        result = extract_actions(
            "刚才拿了两个出来煎给你了。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 0

    def test_take_omitted_subject_ambiguous_context_stays_unresolved(self):
        result = extract_actions(
            "刚才拿了两个出来煎给你了。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
            context_text="用户：面条和面包怎么分",
        )
        assert len(result.candidates) == 0


class TestMultiActionSentence:
    def test_create_and_consume_without_comma(self):
        result = extract_actions(
            "我做了面用了两个鸡蛋。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 2
        assert result.candidates[0].action_type == "CREATE"
        assert result.candidates[0].target.name == "面"
        assert result.candidates[1].action_type == "CONSUME"
        assert result.candidates[1].target.name == "鸡蛋"
        assert result.candidates[1].quantity == 2.0


class TestNoiseFiltering:
    def test_question_filtered(self):
        result = extract_actions(
            "你想吃鸡蛋吗？",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 0

    def test_hypothetical_filtered(self):
        result = extract_actions(
            "如果饿了我可以做面。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 0

    def test_future_filtered(self):
        result = extract_actions(
            "待会我给你做鸡蛋卷。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 0


class TestEdgeCases:
    def test_empty_reply(self):
        result = extract_actions("", known_object_names=KNOWN_NAMES, turn_ref=_tr())
        assert len(result.candidates) == 0
        assert result.skipped_reason == "empty_reply"

    def test_none_reply(self):
        result = extract_actions(None, known_object_names=KNOWN_NAMES, turn_ref=_tr())
        assert len(result.candidates) == 0

    def test_no_known_names(self):
        result = extract_actions(
            "我用了鸡蛋。",
            known_object_names=set(),
            turn_ref=_tr(),
        )
        assert len(result.candidates) == 0

    def test_deterministic(self):
        reply = "我用了两个鸡蛋。"
        results = [
            extract_actions(reply, known_object_names=KNOWN_NAMES, turn_ref=_tr())
            for _ in range(10)
        ]
        for r in results:
            assert len(r.candidates) == len(results[0].candidates)
            for a, b in zip(r.candidates, results[0].candidates):
                assert a.action_type == b.action_type
                assert a.target.name == b.target.name
                assert a.quantity == b.quantity

    def test_dedupe_key_stable(self):
        reply = "我用了两个鸡蛋。"
        r1 = extract_actions(reply, known_object_names=KNOWN_NAMES, turn_ref=_tr())
        r2 = extract_actions(reply, known_object_names=KNOWN_NAMES, turn_ref=_tr())
        assert r1.candidates[0].dedupe_key == r2.candidates[0].dedupe_key

    def test_channel_is_lexicon(self):
        result = extract_actions(
            "我用了鸡蛋。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert result.channel == "lexicon"

    def test_metadata_has_evidence(self):
        result = extract_actions(
            "我用了两个鸡蛋。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        assert result.candidates[0].metadata.get("evidence")
        assert result.candidates[0].metadata.get("channel") == "lexicon"

    def test_ordinal_sequential(self):
        result = extract_actions(
            "我用了两个鸡蛋，做好了一碗面。",
            known_object_names=KNOWN_NAMES,
            turn_ref=_tr(),
        )
        if len(result.candidates) >= 2:
            assert result.candidates[0].turn_ref.ordinal < result.candidates[1].turn_ref.ordinal
