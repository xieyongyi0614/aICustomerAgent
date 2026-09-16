"""PLAN-010 Step 1 ~ Step 3：证据通道值集 / 三个计划证据窗 / 三道闸零豁免。

覆盖 Task Detail §9.1（U1 ~ U8）与 §9.2（I1 / I2）。

口径：计划通道是**既有聚合的扩源**，不是新通道——计划窗进 `aggregate_evidence_windows`
的返回列表，于是 `trigger_for_user` 的门槛 / 额度 / 幂等入队三层与用户证据**同一条路径**
（本模块用「两通道逐场景决策相等 + `trigger_for_user` 零计划分支」两条断言把它钉住）。
"""

import inspect
from datetime import timedelta

import pytest

from app.core.db import BackgroundJobRow, ReflectionRunRow
from app.core.settings import get_settings
from app.models.reflection import (
    EVIDENCE_CHANNEL_MEMORY,
    EVIDENCE_CHANNEL_PLAN,
    EVIDENCE_CHANNEL_TOOL,
    EVIDENCE_CHANNELS,
)
from app.services.reflection import evidence as reflection_evidence
from app.services.reflection import triggers

from . import _plan_scan as scan
from .conftest import V25_NOW
from .plan010_support import (
    NOW,
    TOOL_WEATHER,
    USER,
    StubTrace,
    evidence_id,
    fact_series,
    install_llm_probe,
    plan_fact,
    plan_reflection_env,
    plan_reflection_on,
    seed_action_series,
    seed_criteria_series,
    seed_goal,
    seed_plan,
    seed_success_rate_series,
    structure_step,
)

TRIGGERS_PATH = scan.PLANNING_PACKAGE_DIR.parent / "reflection" / "triggers.py"
EVIDENCE_PATH = scan.PLANNING_PACKAGE_DIR.parent / "reflection" / "evidence.py"

PLAN_WINDOWS = reflection_evidence.PLAN_WINDOW_KINDS
GATE_CHAIN = (
    "aggregate_evidence_windows",
    "passes_gate",
    "_quota_used",
    "_channel_bucket_key",
    "has_job",
    "enqueue_job",
)


def _function_code_text(path, name: str) -> str:
    """指定函数的可执行 token 拼接（去注释与字符串，同 `_plan_scan` 代码口径）。"""
    source_lines = path.read_text(encoding="utf-8").splitlines()
    import ast
    import io
    import tokenize

    tree = ast.parse("\n".join(source_lines), filename=str(path))
    node = next(
        item
        for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name == name
    )
    segment = "\n".join(source_lines[node.lineno - 1 : node.end_lineno])
    tokens = [
        token
        for token in tokenize.generate_tokens(io.StringIO(segment).readline)
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    ]
    return "".join(token.string for token in tokens)


def _table_rows(session_factory, model) -> list:
    with session_factory() as session:
        rows = session.query(model).all()
        for row in rows:
            session.expunge(row)
        return list(rows)


def _seed_run(session_factory, *, status: str = "done", at=NOW, user_id: str = USER):
    with session_factory() as session:
        session.add(
            ReflectionRunRow(
                id=f"rr-plan10-{status}",
                user_id=user_id,
                character_id="asuna",
                trigger="event",
                status=status,
                evidence_summary={},
                outcome=None,
                llm_used=False,
                created_at=at,
                updated_at=at,
            )
        )
        session.commit()


def _seed_day_bucket_job(session_factory, *, at=NOW, user_id: str = USER):
    key = triggers._day_bucket_key(user_id, at)
    with session_factory() as session:
        session.add(
            BackgroundJobRow(
                id="job-plan10-bucket",
                job_type=triggers.JOB_TYPE_REFLECTION_RUN,
                payload={},
                status="pending",
                attempts=0,
                run_at=at,
                idempotency_key=key,
                created_at=at,
            )
        )
        session.commit()
    return key


class TestEvidenceChannelValueSet:
    """Step 1 / U1：值集三值，既有两值相对顺序与语义不变。"""

    def test_u1_evidence_channels_are_exactly_three_values(self):
        assert EVIDENCE_CHANNELS == (
            EVIDENCE_CHANNEL_MEMORY,
            EVIDENCE_CHANNEL_TOOL,
            EVIDENCE_CHANNEL_PLAN,
        )
        assert EVIDENCE_CHANNELS == ("memory", "tool", "plan")
        assert len(EVIDENCE_CHANNELS) == 3
        assert EVIDENCE_CHANNEL_PLAN == "plan"

    def test_u1_legacy_channel_prefixes_are_unchanged(self):
        """既有两值是**追加**关系：前两值逐字未动（尾插是唯一合法扩法）。"""
        assert EVIDENCE_CHANNELS[:2] == ("memory", "tool")
        assert triggers.CHANNEL_MEMORY == EVIDENCE_CHANNEL_MEMORY
        assert triggers.CHANNEL_TOOL == EVIDENCE_CHANNEL_TOOL
        assert triggers.CHANNEL_PLAN == EVIDENCE_CHANNEL_PLAN

    def test_u1_plan_window_structure_reuses_the_tool_window_shape(self):
        from app.models.reflection import (
            PLAN_EVIDENCE_KIND,
            PlanEvidenceWindow,
            ToolEvidenceWindow,
        )

        assert issubclass(PlanEvidenceWindow, ToolEvidenceWindow)
        window = PlanEvidenceWindow(topic_digest="窗口")
        assert window.kind == PLAN_EVIDENCE_KIND
        assert window.insight_types == ()


class TestPlanEvidenceWindows:
    """Step 2 / U2 ~ U7：三窗的数据源、分组键、证据 id 与上限常量。"""

    def test_u2_success_rate_window_groups_by_goal_type(self):
        facts = [
            plan_fact(evidence_id=evidence_id("g1", 1, 1), step_status="done"),
            plan_fact(
                evidence_id=evidence_id("g1", 1, 2),
                step_index=2,
                observed_at=NOW - timedelta(hours=30),
                step_status="done",
            ),
            plan_fact(
                evidence_id=evidence_id("g1", 1, 3),
                step_index=3,
                observed_at=NOW - timedelta(hours=60),
                step_status="failed",
            ),
            plan_fact(
                evidence_id=evidence_id("g1", 1, 4),
                step_index=4,
                observed_at=NOW - timedelta(hours=90),
                step_status="failed",
            ),
        ]
        groups = reflection_evidence.aggregate_plan_success_rate(
            USER, now=NOW, facts=facts
        )
        assert list(groups) == ["user_care"]
        entry = groups["user_care"]
        assert entry["group_kind"] == reflection_evidence.GROUP_KIND_PLAN
        assert entry["group_key"] == "user_care"
        assert entry["samples"] == 4
        assert entry["success"] == 2
        assert entry["failed"] == 2
        assert entry["success_rate"] == 0.5
        assert entry["plan_status_counts"] == {"active": 4}
        assert entry["span_hours"] >= 24.0

    def test_u2_non_terminal_steps_do_not_enter_the_success_rate(self):
        facts = [
            plan_fact(step_status="pending", observed_at=None),
            plan_fact(step_index=2, step_status="in_progress", observed_at=None),
        ]
        groups = reflection_evidence.aggregate_plan_success_rate(
            USER, now=NOW, facts=facts
        )
        assert groups == {}

    def test_u3_step_failure_modes_group_by_tool_and_failure_kind(self):
        facts = fact_series(
            count=3,
            step_status="timeout",
            tool_id=TOOL_WEATHER,
            failure_kind="timeout",
        )
        groups = reflection_evidence.aggregate_step_failure_modes(
            USER, now=NOW, facts=facts
        )
        step_entry = groups[f"{reflection_evidence.GROUP_KIND_STEP}:{TOOL_WEATHER}"]
        assert step_entry["group_kind"] == reflection_evidence.GROUP_KIND_STEP
        assert step_entry["samples"] == 3
        assert step_entry["failed"] == 3
        assert step_entry["timeout"] == 3
        assert step_entry["failure_kinds"] == {"timeout": 3}
        failure_entry = groups[
            f"{reflection_evidence.GROUP_KIND_FAILURE}:{TOOL_WEATHER}|timeout"
        ]
        assert failure_entry["group_kind"] == reflection_evidence.GROUP_KIND_FAILURE
        assert failure_entry["parent_tool_id"] == TOOL_WEATHER
        assert failure_entry["failure_kind"] == "timeout"
        assert failure_entry["samples"] == 3

    def test_u4_criteria_decidability_groups_by_criteria_kind(self):
        facts = fact_series(
            count=3, step_status="in_progress", criteria_kind="field_equals", undecided=True
        ) + fact_series(
            count=1, step_status="done", criteria_kind="field_equals"
        )
        groups = reflection_evidence.aggregate_criteria_decidability(
            USER, now=NOW, facts=facts
        )
        entry = groups["field_equals"]
        assert entry["group_kind"] == reflection_evidence.GROUP_KIND_CRITERIA
        assert entry["samples"] == 4
        assert entry["undecided"] == 3
        assert entry["decided"] == 1
        assert entry["undecided_rate"] == 0.75

    def test_u5_plan_windows_reuse_the_existing_caps_and_constants(self):
        settings = get_settings()
        base = reflection_evidence.plan_thresholds(
            reflection_evidence.PLAN_WINDOW_SUCCESS_RATE
        )
        assert base["min_samples"] == settings.v25_plan_reflection_min_samples
        assert base["min_span_hours"] == settings.v2_reflection_min_span_hours
        assert base["min_failures"] == settings.v25_plan_reflection_min_samples
        assert reflection_evidence.PLAN_WINDOW_FAILURE_DRIVEN_KINDS == PLAN_WINDOWS

    def test_u5_plan_module_does_not_redeclare_the_existing_caps(self):
        """上限常量只允许复用：计划段不得出现新造的上限字面量。"""
        source = EVIDENCE_PATH.read_text(encoding="utf-8")
        plan_section = source.split("# --- PLAN-010", 1)[1]
        assert "TOOL_EVIDENCE_WINDOW_DAYS" in plan_section
        assert "TOOL_EVIDENCE_MAX_MEMBERS" in plan_section
        assert "TOOL_EVIDENCE_RECORD_SCAN_LIMIT" in plan_section
        assert "PLAN_EVIDENCE_WINDOW_DAYS = " not in plan_section
        assert "PLAN_EVIDENCE_MAX_MEMBERS = " not in plan_section
        assert "PLAN_EVIDENCE_RECORD_SCAN_LIMIT = " not in plan_section

    def test_u6_group_kind_names_follow_the_existing_paradigm(self):
        assert reflection_evidence.GROUP_KIND_PLAN == "plan_kind"
        assert reflection_evidence.GROUP_KIND_STEP == "step_kind"
        assert reflection_evidence.GROUP_KIND_CRITERIA == "criteria_kind"
        assert reflection_evidence.GROUP_KIND_FAILURE == "failure_kind"
        assert reflection_evidence.GROUP_KIND_TOOL == "tool_id"

    def test_u7_evidence_id_follows_the_frozen_template(self):
        assert reflection_evidence.plan_evidence_id("g-1", 2, 3) == "plan:g-1:2:3"
        assert reflection_evidence.PLAN_STEP_EVIDENCE_PREFIX == "plan:"
        assert reflection_evidence.plan_evidence_id_of("plan:g-1:2:3") == ("g-1", 2, 3)
        assert reflection_evidence.plan_evidence_id_of("goal:g-1:2:3") is None
        assert reflection_evidence.plan_evidence_id_of("") is None
        assert reflection_evidence.plan_evidence_id_of("plan:x:y:3") is None

    def test_u7_plan_windows_carry_evidence_ids_in_the_frozen_form(self):
        facts = fact_series(
            count=3, step_status="failed", tool_id=TOOL_WEATHER, failure_kind="timeout"
        )
        groups = reflection_evidence.aggregate_step_failure_modes(
            USER, now=NOW, facts=facts
        )
        windows = reflection_evidence.build_plan_evidence_windows(
            {reflection_evidence.PLAN_WINDOW_STEP_FAILURE: groups},
            facts,
            now=NOW,
        )
        assert len(windows) == 2
        for window in windows:
            for member in window.members:
                assert member.memory_id.startswith("plan:")
                assert reflection_evidence.plan_evidence_id_of(member.memory_id)

    def test_plan_window_gate_uses_the_existing_gate_function(self):
        """D7：门槛判定复用 `passes_tool_gate` / `tool_gate_reasons`，不自造数学。"""
        source = EVIDENCE_PATH.read_text(encoding="utf-8")
        plan_section = source.split("# --- PLAN-010", 1)[1]
        assert "passes_tool_gate(" in plan_section
        assert "tool_gate_reasons(" in plan_section
        assert "passes_plan_gate" not in plan_section

    def test_plan_window_insight_types_are_bounded(self):
        allowed = reflection_evidence.PLAN_WINDOW_ALLOWED_INSIGHTS
        assert set(allowed) == set(PLAN_WINDOWS)
        for kinds in allowed.values():
            assert set(kinds) <= {"capability_note", "pattern", "usage_preference"}
        assert "interaction_calibration" not in {
            kind for kinds in allowed.values() for kind in kinds
        }


class TestPlanEvidenceFromProjections:
    """Step 2：三窗各有一条**真实投影**场景（DB 只读面），并验证门槛与上限。"""

    def test_s2_success_rate_window_passes_the_gate_from_goal_plans(
        self, db_session_factory, plan_reflection_on
    ):
        goal, _plan = seed_success_rate_series()
        package = reflection_evidence.aggregate_plan_evidence(USER, now=NOW)
        assert package.steps == 4
        assert package.passing == 1
        window = package.windows[0]
        assert window.window_kind == reflection_evidence.PLAN_WINDOW_SUCCESS_RATE
        assert window.group_key == "user_care"
        assert window.passes_gate is True
        assert window.insight_types == ("capability_note",)
        assert window.stats.member_count == 4
        assert window.stats.span_hours >= 24.0
        assert goal.id in window.members[0].memory_id

    def test_s2_step_failure_window_passes_the_gate_from_action_records(
        self, db_session_factory, plan_reflection_on
    ):
        goal = seed_goal(description="查天气总是超时")
        seed_action_series(goal_id=goal.id, count=3, tool_id=TOOL_WEATHER)
        package = reflection_evidence.aggregate_plan_evidence(USER, now=NOW)
        kinds = {window.window_kind for window in package.windows}
        assert reflection_evidence.PLAN_WINDOW_STEP_FAILURE in kinds
        window = next(
            item
            for item in package.windows
            if item.window_kind == reflection_evidence.PLAN_WINDOW_STEP_FAILURE
            and item.group_key == TOOL_WEATHER
        )
        assert window.insight_types == ("capability_note", "usage_preference")
        assert window.members[0].memory_id == evidence_id(goal.id, 1, 1)

    def test_s3_criteria_decidability_window_passes_the_gate_from_sub_goals(
        self, db_session_factory, plan_reflection_on
    ):
        seed_criteria_series(undecided=3, decided=1)
        package = reflection_evidence.aggregate_plan_evidence(USER, now=NOW)
        window = next(
            item
            for item in package.windows
            if item.window_kind == reflection_evidence.PLAN_WINDOW_CRITERIA_DECIDABILITY
        )
        assert window.group_key == "field_equals"
        assert window.insight_types == ("pattern",)
        assert window.stats.member_count == 4

    def test_members_are_bounded_by_the_existing_cap(
        self, db_session_factory, plan_reflection_on
    ):
        goal = seed_goal(description="上限目标")
        specs = [
            structure_step(
                index,
                status="failed",
                attempt_count=2,
                observed_at=NOW - timedelta(hours=8 * index),
            )
            for index in range(1, 20)
        ]
        seed_plan(goal.id, specs)
        package = reflection_evidence.aggregate_plan_evidence(USER, now=NOW)
        window = package.windows[0]
        assert window.stats.member_count == reflection_evidence.TOOL_EVIDENCE_MAX_MEMBERS

    def test_other_users_and_non_plan_records_are_not_projected(
        self, db_session_factory, plan_reflection_on
    ):
        from .plan010_support import OTHER_USER, action_record, seed_action_series

        seed_success_rate_series(user_id=OTHER_USER)
        goal = seed_goal(description="非计划域台账")
        seed_action_series(goal_id=goal.id, count=1)
        from app.repositories import action_repository

        action_repository.save_record(
            action_record(goal.id, record_id="legacy-1", dedupe_key="goal:g:1:1")
        )
        package = reflection_evidence.aggregate_plan_evidence(USER, now=NOW)
        assert package.windows == []
        assert package.steps == 0

    def test_plan_evidence_is_off_without_the_sub_flag(
        self, db_session_factory, override_settings
    ):
        """D14：子闸 off → 计划窗零产出、零额外读取（证据聚合只有两通道）。"""
        plan_reflection_env(override_settings)
        override_settings(v25_plan_reflection_enabled="false")
        seed_success_rate_series()
        package = reflection_evidence.aggregate_plan_evidence(USER, now=NOW)
        assert package.windows == []
        assert package.passing == 0
        windows = reflection_evidence.aggregate_evidence_windows(USER, now=NOW)
        assert all(
            getattr(window, "window_kind", "") not in PLAN_WINDOWS for window in windows
        )
        assert reflection_evidence.plan_evidence_enabled() is False


class TestPlanEvidenceReachesTheReflector:
    """Step 2 / U8：证据不足零 LLM；证据足够时窗口进既有聚合（reflector 零改动可见）。"""

    def test_u8_insufficient_evidence_yields_no_window_and_no_llm(
        self, db_session_factory, plan_reflection_on, monkeypatch
    ):
        goal = seed_goal(description="样本不足目标")
        seed_plan(
            goal.id,
            [
                structure_step(1, status="done", observed_at=NOW - timedelta(hours=30)),
                structure_step(2, status="failed", attempt_count=2),
            ],
        )
        probe = install_llm_probe(monkeypatch)
        package = reflection_evidence.aggregate_plan_evidence(USER, now=NOW)
        assert package.windows == []
        assert package.passing == 0
        assert triggers.trigger_for_user(USER, now=NOW) == triggers.OUTCOME_SKIPPED
        assert probe.calls == 0
        runs = _table_rows(db_session_factory, ReflectionRunRow)
        assert [row.status for row in runs] == ["skipped"]
        assert _table_rows(db_session_factory, BackgroundJobRow) == []

    def test_insufficient_span_keeps_the_window_out(self, db_session_factory, plan_reflection_on):
        goal = seed_goal(description="跨度不足目标")
        specs = [
            structure_step(
                index, status="done", observed_at=NOW - timedelta(minutes=10 * index)
            )
            for index in range(1, 5)
        ]
        seed_plan(goal.id, specs)
        package = reflection_evidence.aggregate_plan_evidence(USER, now=NOW)
        assert package.windows == []

    def test_plan_windows_are_appended_to_the_shared_aggregation(
        self, db_session_factory, plan_reflection_on
    ):
        seed_success_rate_series()
        windows = reflection_evidence.aggregate_evidence_windows(USER, now=NOW)
        assert [window.window_kind for window in windows] == [
            reflection_evidence.PLAN_WINDOW_SUCCESS_RATE
        ]
        assert windows[0].passes_gate is True

    def test_plan_evidence_traces_under_its_own_step_name(
        self, db_session_factory, plan_reflection_on
    ):
        seed_success_rate_series()
        trace = StubTrace()
        reflection_evidence.aggregate_plan_evidence(USER, now=NOW, trace=trace)
        assert reflection_evidence.PLAN_EVIDENCE_STEP_NAME in trace.names


class TestThreeGatesAreShared:
    """Step 3 / I1：计划证据与用户证据走**完全相同**的三道闸（零豁免）。"""

    @pytest.mark.parametrize("case", ["queued", "quota_row", "quota_job", "no_evidence"])
    def test_i1_both_channels_share_the_same_gate_chain(
        self, db_session_factory, plan_reflection_on, case
    ):
        if case != "no_evidence":
            seed_success_rate_series()
        if case == "quota_row":
            _seed_run(db_session_factory, status="done")
        if case == "quota_job":
            _seed_day_bucket_job(db_session_factory)
        expected = {
            "queued": triggers.OUTCOME_QUEUED,
            "quota_row": triggers.OUTCOME_QUOTA,
            "quota_job": triggers.OUTCOME_QUOTA,
            "no_evidence": triggers.OUTCOME_SKIPPED,
        }[case]
        plan_decision = triggers.trigger_for_user(
            USER, now=NOW, channel=triggers.CHANNEL_PLAN
        )
        assert plan_decision == expected
        memory_decision = triggers.trigger_for_user(
            USER, now=NOW, channel=triggers.CHANNEL_MEMORY
        )
        if case == "queued":
            # 共享状态：首次入队后，第二通道走同一额度 / 幂等键（deduped）。
            assert memory_decision == triggers.OUTCOME_QUOTA
        else:
            assert memory_decision == expected

    def test_i1_plan_evidence_is_gated_by_the_same_threshold(
        self, db_session_factory, plan_reflection_on
    ):
        """闸一：计划窗与用户证据同用一个 `passes_gate`（同一份 settings 门槛）。"""
        goal = seed_goal(description="门槛对照目标")
        seed_plan(
            goal.id,
            [
                structure_step(1, status="done", observed_at=NOW - timedelta(hours=30)),
                structure_step(2, status="failed", attempt_count=2),
            ],
        )
        windows = reflection_evidence.aggregate_evidence_windows(USER, now=NOW)
        assert all(window.passes_gate is False for window in windows)
        assert triggers.trigger_for_user(
            USER, now=NOW, channel=triggers.CHANNEL_PLAN
        ) == triggers.OUTCOME_SKIPPED

    def test_i1_quota_and_idempotency_are_shared_with_the_user_channel(
        self, db_session_factory, plan_reflection_on
    ):
        """闸二 / 闸三：额度按当日 run 行计、幂等键为既有日桶（计划通道不另立）。"""
        seed_success_rate_series()
        assert triggers._quota_used(USER, NOW) is False
        assert triggers._channel_bucket_key(
            USER, NOW, triggers.CHANNEL_PLAN
        ) == triggers._channel_bucket_key(USER, NOW, triggers.CHANNEL_MEMORY)
        assert triggers.trigger_for_user(
            USER, now=NOW, channel=triggers.CHANNEL_PLAN
        ) == triggers.OUTCOME_QUEUED
        assert triggers._quota_used(USER, NOW) is True
        assert triggers.trigger_for_user(
            USER, now=NOW, channel=triggers.CHANNEL_PLAN
        ) == triggers.OUTCOME_QUOTA

    def test_i1_plan_run_summary_lands_like_a_user_run(
        self, db_session_factory, plan_reflection_on
    ):
        """计划窗达门槛时，落库的 run 行带着该窗口（与用户证据同形）。"""
        seed_success_rate_series()
        assert triggers.trigger_for_user(
            USER, now=NOW, channel=triggers.CHANNEL_PLAN
        ) == triggers.OUTCOME_QUEUED
        runs = _table_rows(db_session_factory, ReflectionRunRow)
        assert len(runs) == 1
        summary = runs[0].evidence_summary
        assert summary["passing"] == 1
        assert summary["windows"][0]["member_count"] == 4
        jobs = _table_rows(db_session_factory, BackgroundJobRow)
        assert [job.idempotency_key for job in jobs] == [
            triggers._day_bucket_key(USER, NOW)
        ]


class TestTriggerForUserIsUntouched:
    """I2：`trigger_for_user` 的闸门逻辑 diff 为空（零计划分支、闸序冻结）。"""

    def test_i2_gate_chain_order_is_frozen(self):
        text = _function_code_text(TRIGGERS_PATH, "trigger_for_user")
        positions = [text.index(fragment) for fragment in GATE_CHAIN]
        assert positions == sorted(positions)
        for fragment in ("passes_gate", "_quota_used", "has_job", "enqueue_job"):
            assert text.count(fragment) == 1, fragment

    def test_i2_the_gate_function_has_no_plan_branch(self):
        text = _function_code_text(TRIGGERS_PATH, "trigger_for_user").lower()
        assert "plan" not in text
        assert scan.code_text(TRIGGERS_PATH).count("CHANNEL_PLAN=") == 1

    def test_i2_signature_and_off_semantics_are_unchanged(self):
        params = list(inspect.signature(triggers.trigger_for_user).parameters)
        assert params == [
            "user_id",
            "character_id",
            "trigger",
            "now",
            "trace",
            "channel",
        ]
        assert (
            inspect.signature(triggers.trigger_for_user).parameters["channel"].default
            == triggers.CHANNEL_MEMORY
        )

    def test_i2_plan_channel_is_an_alias_not_a_second_path(self):
        assert triggers.CHANNEL_PLAN == EVIDENCE_CHANNEL_PLAN
        source = TRIGGERS_PATH.read_text(encoding="utf-8")
        assert "CHANNEL_PLAN = EVIDENCE_CHANNEL_PLAN" in source
        assert "channel == CHANNEL_PLAN" not in source

    def test_i2_existing_tool_channel_still_has_its_own_branch(self):
        """工具通道的既有子闸与幂等键一字未改（与计划通道的差别正在于此）。"""
        text = _function_code_text(TRIGGERS_PATH, "trigger_for_user")
        assert "channel==CHANNEL_TOOL" in text
        text_key = _function_code_text(TRIGGERS_PATH, "_channel_bucket_key")
        assert "reflect:tool:" in TRIGGERS_PATH.read_text(encoding="utf-8")
        assert "CHANNEL_TOOL" in text_key

    def test_i2_evidence_aggregation_only_adds_plan_windows_at_the_end(self):
        """计划窗**追加**在既有窗口之后（既有窗口的相对顺序与优先序不变）。"""
        source = EVIDENCE_PATH.read_text(encoding="utf-8")
        assert (
            'return result["windows"] + _plan_channel_windows(user_id, now, trace)'
            in source
        )

    def test_i2_memory_channel_windows_are_unchanged_without_the_sub_flag(
        self, db_session_factory, override_settings, monkeypatch
    ):
        from app.models.reflection import EvidenceMember, EvidenceWindow, WindowStats

        override_settings(v2_reflection_enabled="true", v25_plan_reflection_enabled="false")
        window = EvidenceWindow(
            topic_digest="既有窗口",
            members=[
                EvidenceMember(
                    memory_id="m1",
                    content="记忆一",
                    created_at=V25_NOW,
                    source="user_stated",
                    source_ref="m1",
                    salience=0.5,
                    weight=0.5,
                )
            ],
            stats=WindowStats(
                member_count=1, span_hours=1.0, distinct_source_refs=1, coherence=1.0
            ),
        )
        monkeypatch.setattr(
            reflection_evidence,
            "_aggregate",
            lambda *args, **kwargs: {
                "pool_size": 1,
                "clusters": 1,
                "windows": [window],
                "degraded": None,
            },
        )
        seed_success_rate_series()
        assert reflection_evidence.aggregate_evidence_windows(USER, now=NOW) == [window]
