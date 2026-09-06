"""DEV-005：Trace 与评估接入。

trace 步骤名单注册、development 4 规则表驱动（切片缺席跳过/命中各码）、
debug 归因端点（state 全链 + 404 + 用户列表）、离线场景集 E-DEV-01~03
（注入式 runner + compute_metrics，Gate 全过）、build_db_report 与
offline_evaluator development 小节、Flag OFF 空跑。
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool

from app.core.db import DevelopmentChangeRow, DevelopmentStateRow
from app.main import app
from app.services.development import aggregate
from app.services.development import evaluation as development_evaluation
from app.services.evaluation_context import DevelopmentChangeRef, DevelopmentStateRef, DevelopmentSlice
from app.services.evaluation_rules import run_rules
from app.services.evaluation_rules.development import (
    ChangeUnattributedRule,
    ConcurrentActiveRule,
    OverCapRule,
    StaleActiveRule,
)
from app.services.trace_collector import TRACE_STEP_NAMES

pytestmark = pytest.mark.xdist_group("development")

USER = "u-dev5"


def _seed_state(
    session_factory,
    state_id,
    key,
    value,
    *,
    strength=0.8,
    insight_id="ins-5",
    status="active",
    kind="preference",
):
    now = datetime.now()
    with session_factory() as session:
        session.add(
            DevelopmentStateRow(
                id=state_id,
                user_id=USER,
                character_id="asuna",
                kind=kind,
                key=key,
                value=value,
                strength=strength,
                source_insight_id=insight_id,
                status=status,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _seed_change(session_factory, change_id, state_id, *, insight_id="ins-5"):
    now = datetime.now()
    with session_factory() as session:
        session.add(
            DevelopmentChangeRow(
                id=change_id,
                development_state_id=state_id,
                before=None,
                after={"max_tokens_delta": -150},
                insight_id=insight_id,
                reason="compiled",
                created_at=now,
            )
        )
        session.commit()


def test_trace_step_names_registered():
    for name in (
        "development_state",
        "development_compile",
        "development_apply",
        "development_rollback",
    ):
        assert name in TRACE_STEP_NAMES


def _slice(states=None, changes=None, insight_statuses=None) -> DevelopmentSlice:
    return DevelopmentSlice(
        active_states=states or [],
        changes=changes or [],
        insight_statuses=insight_statuses or {},
    )


def _state(key="response_style.length", value=None, strength=0.8, insight_id="ins-5"):
    return DevelopmentStateRef(
        id=f"dev-{key}",
        key=key,
        kind="preference",
        status="active",
        strength=strength,
        value=value if value is not None else {"max_tokens_delta": -150},
        source_insight_id=insight_id,
    )


def _change(insight_id="ins-5", change_id="devc-1") -> DevelopmentChangeRef:
    return DevelopmentChangeRef(
        id=change_id,
        state_id="dev-x",
        insight_id=insight_id,
        reason="compiled",
    )


def test_rule_skips_when_slice_absent():
    ctx = _ctx(None)
    assert ChangeUnattributedRule().evaluate(ctx) is None
    assert ConcurrentActiveRule().evaluate(ctx) is None
    assert OverCapRule().evaluate(ctx) is None
    assert StaleActiveRule().evaluate(ctx) is None


def _ctx(development: DevelopmentSlice | None):
    from app.services.evaluation_context import EvaluationContext

    return EvaluationContext(
        subject="offline_batch",
        subject_id="batch-1",
        session_id="s",
        user_id=USER,
        development=development,
    )


def test_unattributed_rule_detects_missing_and_dangling():
    rule = ChangeUnattributedRule()
    ok = rule.evaluate(_ctx(_slice(changes=[_change()], insight_statuses={"ins-5": "active"})))
    assert ok is None
    missing = rule.evaluate(_ctx(_slice(changes=[_change(insight_id="")], insight_statuses={})))
    assert missing is not None and missing.code.value == "development_change_unattributed"
    dangling = rule.evaluate(
        _ctx(_slice(changes=[_change(insight_id="ins-gone")], insight_statuses={}))
    )
    assert dangling is not None


def test_concurrent_active_rule_detects_duplicate_key():
    rule = ConcurrentActiveRule()
    ok = rule.evaluate(_ctx(_slice(states=[_state()])))
    assert ok is None
    issue = rule.evaluate(
        _ctx(_slice(states=[_state(insight_id="a"), _state(insight_id="b")]))
    )
    assert issue is not None and "2 条 active" in issue.evidence_quote


def test_over_cap_rule_checks_amplitude():
    rule = OverCapRule()
    ok = rule.evaluate(_ctx(_slice(states=[_state(value={"max_tokens_delta": -160})])))
    assert ok is None
    issue = rule.evaluate(
        _ctx(_slice(states=[_state(value={"max_tokens_delta": -500}, strength=0.8)]))
    )
    assert issue is not None and issue.code.value == "development_over_cap"


def test_stale_active_rule_detects_invalidated_source():
    rule = StaleActiveRule()
    ok = rule.evaluate(
        _ctx(_slice(states=[_state()], insight_statuses={"ins-5": "active"}))
    )
    assert ok is None
    issue = rule.evaluate(
        _ctx(_slice(states=[_state()], insight_statuses={"ins-5": "invalidated"}))
    )
    assert issue is not None and issue.code.value == "development_stale_active"


def test_rules_registered_in_engine():
    from app.services.evaluation_rules import RULES

    codes = {type(rule).code for rule in RULES}
    assert {
        ChangeUnattributedRule.code,
        ConcurrentActiveRule.code,
        OverCapRule.code,
        StaleActiveRule.code,
    } <= codes


def test_debug_endpoints(db_session_factory):
    _seed_state(db_session_factory, "dev-dbg", "response_style.length", {"max_tokens_delta": -150})
    _seed_change(db_session_factory, "devc-dbg", "dev-dbg")
    client = TestClient(app)
    response = client.get("/api/v1/debug/development/states/dev-dbg")
    assert response.status_code == 200
    body = response.json()
    assert body["state"]["key"] == "response_style.length"
    assert body["changes"][0]["insight_id"] == "ins-5"
    missing = client.get("/api/v1/debug/development/states/missing")
    assert missing.status_code == 404
    listing = client.get(f"/api/v1/debug/development/users/{USER}")
    assert listing.status_code == 200
    assert listing.json()[0]["source_insight_id"] == "ins-5"


def test_offline_scenarios_pass_gate(db_session_factory):
    results = development_evaluation.run_scenarios(db_session_factory)
    report = development_evaluation.compute_metrics(results)
    assert report["failed_scenarios"] == []
    assert report["gate_passed"] is True
    for metric_id in ("E-DEV-01", "E-DEV-02", "E-DEV-03"):
        assert report["metrics"][metric_id]["pass"] is True


def test_build_db_report_flag_off_empty(override_settings):
    override_settings(v2_development_enabled=False)
    assert development_evaluation.build_db_report() == {}


def test_build_db_report_counts(db_session_factory, override_settings):
    override_settings(v2_development_enabled=True)
    from app.core.db import InsightRow

    now = datetime.now()
    with db_session_factory() as session:
        session.add(
            InsightRow(
                id="ins-5",
                user_id=USER,
                character_id="asuna",
                statement="用户偏好简短的回复",
                type="preference",
                confidence=0.8,
                scope="user",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    _seed_state(db_session_factory, "dev-r1", "response_style.length", {"max_tokens_delta": -150})
    _seed_change(db_session_factory, "devc-r1", "dev-r1")
    report = development_evaluation.build_db_report()
    assert report["states_total"] >= 1
    assert report["active_states"] >= 1
    assert report["attribution_rate"] == 1.0
    assert report["concurrent_active_keys"] == 0


def test_collect_slice_flag_off_none(db_session_factory, override_settings):
    override_settings(v2_development_enabled=False)
    assert development_evaluation.collect_slice(USER) is None
