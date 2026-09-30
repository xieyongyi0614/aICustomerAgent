from app.services.evaluation.context import (
    EvaluationContext,
    MemoryRef,
    RecentMessage,
)
from app.services.evaluation.rules import memory as memory_rules


def make_ctx(
    reply: str = "好的，我知道了。",
    memories: list[MemoryRef] | None = None,
    recent: list[RecentMessage] | None = None,
    user_message: str = "我们周末去吃什么好呢？",
) -> EvaluationContext:
    return EvaluationContext(
        subject="turn",
        subject_id="1",
        session_id="c",
        user_id="u",
        user_message=user_message,
        reply=reply,
        injected_memories=memories or [],
        recent_messages=recent or [],
    )


def test_fabrication_candidate_hits_without_support():
    issue = memory_rules.FABRICATION_CANDIDATE.evaluate(
        make_ctx(reply="你最喜欢的草莓蛋糕，我记得你说过。")
    )
    assert issue is not None
    assert issue.code == "memory_fabrication_candidate"
    assert issue.severity == "warning"
    assert "你最喜欢" in issue.evidence_quote


def test_fabrication_candidate_skips_memory_support():
    issue = memory_rules.FABRICATION_CANDIDATE.evaluate(
        make_ctx(
            reply="你最喜欢的草莓蛋糕，我记得你说过。",
            memories=[MemoryRef(id="m1", type="user_preference", content="用户最喜欢草莓蛋糕", importance=0.8)],
        )
    )
    assert issue is None


def test_fabrication_candidate_skips_recent_human_support():
    issue = memory_rules.FABRICATION_CANDIDATE.evaluate(
        make_ctx(
            reply="你最讨厌香菜对吧。",
            recent=[RecentMessage(role="human", content="我最讨厌香菜了")],
        )
    )
    assert issue is None


def test_fabrication_candidate_clean_reply():
    assert memory_rules.FABRICATION_CANDIDATE.evaluate(make_ctx()) is None


def test_missed_memory_hits_when_ignored():
    issue = memory_rules.MISSED.evaluate(
        make_ctx(
            memories=[MemoryRef(id="m1", type="user_fact", content="用户对花生过敏", importance=0.9)],
            user_message="花生过敏的话火锅要避开吗？",
        )
    )
    assert issue is not None
    assert issue.code == "memory_missed"
    assert issue.severity == "info"
    assert "m1" in issue.evidence_quote


def test_missed_memory_skips_used_memory():
    issue = memory_rules.MISSED.evaluate(
        make_ctx(
            reply="花生酱火锅不行哦，你对花生过敏的，我们换别的吧。",
            memories=[MemoryRef(id="m1", type="user_fact", content="用户花生过敏住院", importance=0.9)],
            user_message="我们周末去吃花生酱火锅好不好？",
        )
    )
    assert issue is None


def test_missed_memory_skips_low_importance():
    issue = memory_rules.MISSED.evaluate(
        make_ctx(
            memories=[MemoryRef(id="m2", type="user_fact", content="用户花生过敏住院", importance=0.4)],
            user_message="我们周末去吃花生酱火锅好不好？",
        )
    )
    assert issue is None


def test_missed_memory_skips_irrelevant():
    issue = memory_rules.MISSED.evaluate(
        make_ctx(
            memories=[MemoryRef(id="m1", type="user_fact", content="用户花生过敏住院", importance=0.9)],
            user_message="今天天气真好啊。",
        )
    )
    assert issue is None


def test_rules_registered():
    from app.services.evaluation import rules as evaluation_rules

    codes = {rule.code for rule in evaluation_rules.RULES}
    assert "memory_fabrication_candidate" in codes
    assert "memory_missed" in codes
    assert "emotion_untriggered_shift" in codes
    assert "emotion_text_state_conflict" in codes
