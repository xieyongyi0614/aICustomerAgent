import pytest

from app.chains import evaluation_judge_chain as judge_chain
from app.models.evaluation_judge import (
    PersonaJudgement,
    ProactiveJudgeResult,
    TurnJudgeResult,
)
from app.prompts.evaluation_judge import build_evaluation_judge_messages

VALID_TURN = {
    "persona": {
        "in_character": True,
        "score": 0.9,
        "codes": [],
        "evidence_quote": "谢谢关心",
        "confidence": 0.8,
    },
    "emotion": {"score": 0.85, "codes": [], "evidence_quote": "", "confidence": 0.7},
    "memory": {"score": 1.0, "codes": [], "memory_ids": ["m1"], "evidence_quote": ""},
}
VALID_PROACTIVE = {
    "autonomy": {"score": 0.8, "codes": [], "evidence_quote": "", "confidence": 0.7},
    "persona": {
        "in_character": True,
        "score": 0.9,
        "codes": [],
        "evidence_quote": "",
        "confidence": 0.8,
    },
}

DIGEST = {
    "reply": "谢谢你的关心，我很好。*微微一笑*",
    "injected_memories": [
        {"id": "m1", "type": "user_preference", "content": "用户喜欢寿司"}
    ],
}


async def test_judge_turn_structured_dispatch(fake_llm):
    llm = fake_llm(response="", structured_responses={"TurnJudgeResult": VALID_TURN})
    result = await judge_chain.judge_turn(DIGEST, llm=llm)
    assert isinstance(result, TurnJudgeResult)
    assert result.persona.score == pytest.approx(0.9)
    assert result.memory.memory_ids == ["m1"]


async def test_judge_turn_sanitizes_invalid_evidence(fake_llm):
    payload = {
        **VALID_TURN,
        "persona": {**VALID_TURN["persona"], "evidence_quote": "这句话不在回复里"},
    }
    llm = fake_llm(response="", structured_responses={"TurnJudgeResult": payload})
    result = await judge_chain.judge_turn(DIGEST, llm=llm)
    assert result.persona.evidence_quote == ""
    assert result.emotion is not None


async def test_judge_turn_restricts_memory_ids(fake_llm):
    payload = {
        **VALID_TURN,
        "memory": {**VALID_TURN["memory"], "memory_ids": ["m1", "m999"]},
    }
    llm = fake_llm(response="", structured_responses={"TurnJudgeResult": payload})
    result = await judge_chain.judge_turn(DIGEST, llm=llm)
    assert result.memory.memory_ids == ["m1"]


async def test_judge_turn_failure_returns_none(fake_llm):
    llm = fake_llm(response="", structured_errors={"TurnJudgeResult": RuntimeError("boom")})
    assert await judge_chain.judge_turn(DIGEST, llm=llm) is None


async def test_judge_proactive_dispatch(fake_llm):
    llm = fake_llm(
        response="", structured_responses={"ProactiveJudgeResult": VALID_PROACTIVE}
    )
    result = await judge_chain.judge_proactive(DIGEST, llm=llm)
    assert isinstance(result, ProactiveJudgeResult)
    assert result.autonomy.score == pytest.approx(0.8)


def test_judge_schema_rejects_out_of_range_score():
    with pytest.raises(Exception):
        TurnJudgeResult.model_validate({"persona": {"score": 1.5, "codes": []}})


def test_sanitize_evidence_helper():
    judgement = PersonaJudgement(score=0.5, evidence_quote="不在回复中")
    sanitized = judge_chain._sanitize_evidence(judgement, "回复原文")
    assert sanitized.evidence_quote == ""
    kept = judge_chain._sanitize_evidence(
        PersonaJudgement(score=0.5, evidence_quote="原文"), "含原文的句子"
    )
    assert kept.evidence_quote == "原文"


def test_judge_messages_escape_braces():
    digest = {**DIGEST, "reply": "含{花括号}的回复"}
    messages = build_evaluation_judge_messages(digest)
    digest_line = [str(m) for m in messages if "【上下文摘要】" in str(m)][0]
    assert "{{花括号}}" in digest_line


def test_judge_messages_proactive_subject():
    messages = build_evaluation_judge_messages(DIGEST, subject="proactive_action")
    joined = "\n".join(str(m) for m in messages)
    assert "autonomy 评审标准" in joined
    assert "无人设豁免" in joined
