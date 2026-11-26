"""PLAN-009 Step 3：候选构造（复用既有摄取 + 按 `event_kind` 调整模板 + 隐私分支）。

覆盖 Task Detail §9.1 U5 / U6 / U8、§9.2 I6、§9.3 S7；对应 §8 Step 3 与 §6.3。

**与 Task Detail §4.2.2 的实现核对（本任务唯一需要裁决的硬冲突，已按裁决落地并留痕）**

> §4.2.2 的备选路径称「复用既有 `ingest_from_goal_completion`（其 `source` 取自目标本身）」——
> 该前提与真实源码不符：`memory/ingest.py` 的该函数**硬编码** `source_kind="ai_inferred"`，
> 且在 `memory_policy` 之外另走 `memory_candidates → memory.evaluator → memories` 通道。
> 故若把它的返回值直接当候选基座，三类终态会被 R1 恒定丢弃（G-MEMORY 不成立）；若把它当写入
> 路径，则违反 D8「R1~R8 零豁免」。裁决（用户）：**完成类复用其候选语义与幂等锚点，失败 / 放弃
> 类走 §4.2.2 的加权重路径**（内容锚定目标描述 + 未完成语义 + `importance ≥ floor`），
> 候选的 `type` / `importance` / `source` 一律取自判据 B。
> 两条举证：`test_completed_reuses_the_existing_ingest_verbatim`（复用可追溯）与
> `test_the_reused_row_would_be_rejected_by_r1`（若不覆盖 `source`，R1 会拒收）。
"""

from app.engines import memory_policy as policy_gate
from app.services.planning import memory_policy as plan_memory_policy
from app.services.tool import memory_policy as tool_memory_policy

from . import plan009_support as support

MODULE_PATH = support.module_path("memory_policy.py")

POLICY = plan_memory_policy.PlanMemoryPolicy()


class TestCompletedCandidate:
    """U5 半边 / I6：完成类复用既有摄取（内容 = 完成语义 = 既有候选行的内容）。"""

    def test_completed_reuses_the_existing_ingest_verbatim(self, monkeypatch):
        calls = support.install_ingest_stub(monkeypatch)
        goal = support.goal(support.COMPLETED_DESCRIPTION)
        plan = support.plan()

        candidate = plan_memory_policy.build_candidate(
            goal, plan, plan_memory_policy.EVENT_PLAN_COMPLETED
        )

        assert calls == [(goal.user_id, goal.id, goal.description)]
        assert candidate.content == f"完成了目标：{support.COMPLETED_DESCRIPTION}"
        assert candidate.action == "save"
        assert candidate.type == tool_memory_policy.DEFAULT_MEMORY_TYPE
        assert candidate.importance == 0.7
        assert candidate.source == "user_derived"

    def test_the_reused_row_would_be_rejected_by_r1(self, db_session_factory, monkeypatch):
        """§4.2.2 ※ 提醒的可判定形式：既有摄取行的 source 是 `ai_inferred`。

        不改写 `source` 的候选必然被 R1 丢弃；本任务的候选因取自判据 B 而通过。
        """
        goal = support.goal(support.COMPLETED_DESCRIPTION)
        content = plan_memory_policy._content_for(
            goal, plan_memory_policy.EVENT_PLAN_COMPLETED
        )
        stored = support.latest_candidate_row(db_session_factory, goal.id)
        assert stored is not None
        assert stored.source == "ai_inferred"
        assert content == stored.content

        unrepaired = policy_gate.apply_policy([_candidate_of(content, "ai_inferred")])
        assert [outcome.rule for outcome in unrepaired.discarded] == ["R1"]

    def test_candidate_is_rejected_when_the_ingest_returns_no_row(self, monkeypatch):
        support.install_ingest_stub(monkeypatch, content="")
        assert (
            plan_memory_policy.build_candidate(
                support.goal(),
                support.plan(),
                plan_memory_policy.EVENT_PLAN_COMPLETED,
            )
            is None
        )


class TestUnfinishedCandidates:
    """U5 半边：失败 / 放弃类带未完成语义（措辞复用 V9 失败纪律）。"""

    def test_failed_candidate_carries_unfinished_semantics(self, monkeypatch):
        calls = support.install_ingest_stub(monkeypatch)
        goal = support.goal(support.FAILED_DESCRIPTION)

        candidate = plan_memory_policy.build_candidate(
            goal, support.plan(), plan_memory_policy.EVENT_PLAN_FAILED
        )

        assert calls == []
        assert candidate.action == "save"
        assert candidate.content == f"上次没能帮用户完成：{support.FAILED_DESCRIPTION}"
        assert "没能" in candidate.content
        assert candidate.importance == 0.6
        assert candidate.source == "user_derived"

    def test_abandoned_candidate_carries_unfinished_semantics(self, monkeypatch):
        support.install_ingest_stub(monkeypatch)
        goal = support.goal(support.FAILED_DESCRIPTION)

        candidate = plan_memory_policy.build_candidate(
            goal, support.plan(), plan_memory_policy.EVENT_PLAN_ABANDONED
        )

        assert candidate.content == f"上次没能帮用户完成：{support.FAILED_DESCRIPTION}"
        assert candidate.source == "user_derived"

    def test_unfinished_template_matches_the_v9_failure_wording(self):
        from app.character.asuna import tool as character_tool

        assert plan_memory_policy.PLAN_UNFINISHED_CONTENT_TEMPLATE == (
            character_tool.TOOL_MEMORY_FAILURE_TEMPLATE.replace("{content}", "{description}")
        )

    def test_declined_events_never_build_a_candidate(self, monkeypatch):
        calls = support.install_ingest_stub(monkeypatch)
        for event_kind in (
            plan_memory_policy.EVENT_PLAN_CREATED,
            plan_memory_policy.EVENT_PLAN_REVISED,
            plan_memory_policy.EVENT_STEP_SUCCEEDED,
            plan_memory_policy.EVENT_STEP_FAILED,
        ):
            assert plan_memory_policy.build_candidate(support.goal(), support.plan(), event_kind) is None
        assert calls == []


class TestContentBudget:
    """U6 / D7：内容长度 ≤ `MEMORY_CONTENT_MAX_CHARS`（120）。"""

    def test_long_description_is_truncated_for_every_deposit_event(self, monkeypatch):
        support.install_ingest_stub(monkeypatch)
        long_goal = support.raw_goal("旅行" * 200)
        for event_kind in (
            plan_memory_policy.EVENT_PLAN_COMPLETED,
            plan_memory_policy.EVENT_PLAN_FAILED,
            plan_memory_policy.EVENT_PLAN_ABANDONED,
        ):
            candidate = plan_memory_policy.build_candidate(long_goal, support.plan(), event_kind)
            assert len(candidate.content) <= tool_memory_policy.MEMORY_CONTENT_MAX_CHARS

    def test_confidence_reuses_the_tool_side_default(self, monkeypatch):
        support.install_ingest_stub(monkeypatch)
        candidate = plan_memory_policy.build_candidate(
            support.goal(), support.plan(), plan_memory_policy.EVENT_PLAN_COMPLETED
        )
        assert candidate.confidence == tool_memory_policy.DEFAULT_CONFIDENCE


class TestPrivacyBranch:
    """U8 / S7：隐私步骤参数经 R3（`action="forget"`）转隐私执行。"""

    def test_step_params_carrying_a_forget_command_switch_the_candidate_to_forget(
        self, monkeypatch
    ):
        support.install_ingest_stub(monkeypatch)
        plan = support.plan([support.step(params={"content": "忘掉上次面试的细节"})])

        candidate = plan_memory_policy.build_candidate(
            support.goal(), plan, plan_memory_policy.EVENT_PLAN_COMPLETED
        )

        assert candidate.action == "forget"
        assert candidate.content == "上次面试的细节"

    def test_forget_candidate_takes_the_r3_branch(self, monkeypatch):
        support.install_ingest_stub(monkeypatch)
        plan = support.plan([support.step(params={"content": "忘掉上次面试的细节"})])
        candidate = plan_memory_policy.build_candidate(
            support.goal(), plan, plan_memory_policy.EVENT_PLAN_COMPLETED
        )

        report = policy_gate.apply_policy([candidate], [])

        assert report.privacy_items == [candidate]
        assert [outcome.rule for outcome in report.outcomes] == ["R3"]
        assert report.saved == []

    def test_non_command_params_do_not_trigger_the_privacy_branch(self, monkeypatch):
        support.install_ingest_stub(monkeypatch)
        plan = support.plan([support.step(params={"content": "准备面试材料"})])
        candidate = plan_memory_policy.build_candidate(
            support.goal(), plan, plan_memory_policy.EVENT_PLAN_COMPLETED
        )
        assert candidate.action == "save"

    def test_privacy_routing_reuses_the_existing_command_detector(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        assert "memory_commands.detect_command" in source
        assert "ACTION_FORGET" in source


class TestNoNewCandidateConstructor:
    """I6：零新建候选构造器（唯一候选产出点在 `_candidate`，摄取调用点唯一）。"""

    def test_candidate_is_constructed_in_exactly_one_place(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        assert source.count("MemoryCandidate(") == 1
        assert "def _candidate(" in source

    def test_the_ingest_entry_point_is_called_once_from_this_module(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        assert source.count("memory_ingest.ingest_from_goal_completion(") == 1

    def test_module_does_not_reimplement_the_ingest_content_logic(self):
        literals = support.module_literals(MODULE_PATH)
        assert "完成了目标：" not in "".join(literals)


def _candidate_of(content: str, source: str):
    from app.models.memory import MemoryCandidate

    return MemoryCandidate(
        action="save",
        type=tool_memory_policy.DEFAULT_MEMORY_TYPE,
        content=content,
        importance=0.7,
        confidence=tool_memory_policy.DEFAULT_CONFIDENCE,
        source=source,
    )
