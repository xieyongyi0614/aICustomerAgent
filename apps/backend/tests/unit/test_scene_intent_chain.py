import pytest
from pydantic import ValidationError

from app.chains.scene_intent_chain import classify
from app.models.scene import SCENE_INTENT_EXAMPLES


@pytest.mark.parametrize("intent,message", SCENE_INTENT_EXAMPLES)
async def test_classify_parses_each_intent(fake_llm, intent, message):
    llm = fake_llm(
        structured_responses={
            "SceneIntentResult": {
                "intent": intent,
                "confidence": 0.9,
                "reason": "样例",
            }
        }
    )
    result = await classify(message, llm=llm)
    assert result.intent == intent
    assert result.confidence == 0.9


async def test_classify_renders_user_message(fake_llm):
    llm = fake_llm(
        structured_responses={
            "SceneIntentResult": {
                "intent": "request_action",
                "confidence": 0.9,
                "reason": "x",
            }
        }
    )
    await classify("给我拿瓶水", llm=llm)
    rendered = str(llm.seen_messages)
    assert "给我拿瓶水" in rendered


async def test_classify_degrades_on_exception(fake_llm):
    llm = fake_llm(raise_exc=RuntimeError("boom"))
    result = await classify("在吗", llm=llm)
    assert result.intent == "chat"
    assert result.reason == "scene_intent_failed"


async def test_classify_degrades_on_low_confidence(fake_llm):
    llm = fake_llm(
        structured_responses={
            "SceneIntentResult": {
                "intent": "request_action",
                "confidence": 0.2,
                "reason": "x",
            }
        }
    )
    result = await classify("给我拿瓶水", llm=llm)
    assert result.intent == "chat"
    assert result.reason == "low_confidence"


async def test_classify_degrades_on_invalid_intent(fake_llm):
    llm = fake_llm(
        structured_responses={
            "SceneIntentResult": {
                "intent": "dancing",
                "confidence": 0.9,
                "reason": "非法",
            }
        }
    )
    result = await classify("在吗", llm=llm)
    assert result.intent == "chat"
