"""V8-015 World Consistency 评估规则：世界矛盾候选判定。"""

from app.models.evaluation import EvaluationDimension, IssueCode
from app.services.evaluation_context import EvaluationContext
from app.services.evaluation_rules.memory import WORLD_CONSISTENCY

WORLD = {
    "location": "home.living_room",
    "objects": [
        {"name": "西瓜", "state": "eaten", "quantity": 0.0, "status": "destroyed"},
        {"name": "蛋糕", "state": "cut", "quantity": 0.6, "status": "active"},
    ],
}


def _ctx(reply, world=WORLD):
    return EvaluationContext(
        subject="turn",
        subject_id="t1",
        session_id="s1",
        user_id="default-user",
        reply=reply,
        world=world,
    )


def test_claiming_consumed_object_flags_inconsistency():
    issue = WORLD_CONSISTENCY.evaluate(_ctx("冰箱里有西瓜哦，给你切一块～"))
    assert issue is not None
    assert issue.code is IssueCode.MEMORY_WORLD_INCONSISTENCY
    assert issue.dimension is EvaluationDimension.MEMORY
    assert issue.severity.value == "info"


def test_consistent_claim_passes():
    assert WORLD_CONSISTENCY.evaluate(_ctx("蛋糕还剩一些，给你尝尝？".replace("？", "，"))) is None


def test_question_about_object_is_not_a_claim():
    assert WORLD_CONSISTENCY.evaluate(_ctx("冰箱里还有西瓜吗？")) is None


def test_active_object_claims_are_fine():
    assert WORLD_CONSISTENCY.evaluate(_ctx("这里有蛋糕，你尝尝，")) is None


def test_missing_world_slice_disables_rule():
    assert WORLD_CONSISTENCY.evaluate(_ctx("冰箱里有西瓜哦", world=None)) is None


def test_rule_disabled_by_settings(monkeypatch):
    monkeypatch.setenv("EVALUATION_WORLD_CONSISTENCY_ENABLED", "false")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    assert WORLD_CONSISTENCY.evaluate(_ctx("冰箱里有西瓜哦")) is None
    get_settings.cache_clear()
