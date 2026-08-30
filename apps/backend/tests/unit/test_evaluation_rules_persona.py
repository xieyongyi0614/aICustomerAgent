from app.character.asuna.evaluation import PersonaContradictionPattern
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules import persona as persona_rules


def make_ctx(reply: str, mode: str = "default", character_id: str = "asuna") -> EvaluationContext:
    return EvaluationContext(
        subject="turn",
        subject_id="1",
        session_id="c",
        user_id="u",
        character_id=character_id,
        mode=mode,
        reply=reply,
    )


def test_abusive_language_hits_critical():
    issue = persona_rules.ABUSIVE_LANGUAGE.evaluate(make_ctx("你就是个废物！"))
    assert issue is not None
    assert issue.code == "persona_abusive_language"
    assert issue.severity == "critical"
    assert issue.evidence_quote == "废物"


def test_abusive_language_ignores_negated_mention():
    assert persona_rules.ABUSIVE_LANGUAGE.evaluate(make_ctx("请不要再说那种废物之类的词。")) is None
    assert persona_rules.ABUSIVE_LANGUAGE.evaluate(make_ctx("你就是个废物！")) is not None


def test_abusive_language_clean_reply():
    assert persona_rules.ABUSIVE_LANGUAGE.evaluate(make_ctx("今天也一起加油吧。")) is None


def test_contradiction_pattern_hits():
    issue = persona_rules.CONTRADICTION_PATTERN.evaluate(make_ctx("就凭你？也想让我认真？"))
    assert issue is not None
    assert issue.code == "persona_contradiction_pattern"
    assert issue.severity == "warning"
    assert "就凭你" in issue.evidence_quote


def test_contradiction_pattern_mode_whitelist():
    immersive = persona_rules.CONTRADICTION_PATTERN.evaluate(
        make_ctx("再靠近我就杀了你。", mode="immersive")
    )
    assert immersive is None

    default_hit = persona_rules.CONTRADICTION_PATTERN.evaluate(
        make_ctx("再靠近我就杀了你。", mode="default")
    )
    assert default_hit is not None


def test_contradiction_pattern_unknown_character():
    issue = persona_rules.CONTRADICTION_PATTERN.evaluate(
        make_ctx("就凭你？", character_id="other")
    )
    assert issue is None


def test_persona_patterns_loaded_for_asuna():
    patterns = persona_rules._persona_patterns("asuna")
    assert len(patterns) > 0
    assert all(isinstance(p, PersonaContradictionPattern) for p in patterns)


def test_rules_registered():
    from app.services import evaluation_rules

    codes = {rule.code for rule in evaluation_rules.RULES}
    assert "persona_abusive_language" in codes
    assert "persona_contradiction_pattern" in codes
