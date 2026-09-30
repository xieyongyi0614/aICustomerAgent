"""PLAN-009 Step 5：判据 C（工具侧 deposit 决策不被覆盖）与两层判据正交性。

覆盖 Task Detail §9.2 I4 / I6 / I7 / I9、§9.3 S4 / S5；对应 §8 Step 5 与 §4.2.3 / §5.2。

判据 C 的一句话：中间步骤是否沉淀**不由 Planning 决定**——由该步调用的工具按 V2.4.0
`BOUNDARY_TABLE` / `TOOL_MEMORY_TEMPLATES` 决定；本任务只**只读消费**，零覆盖、零新增表。
"""

import pytest

from app.services.planning import memory_policy as plan_memory_policy
from app.services.tool import memory_policy as tool_memory_policy

from . import _plan_scan as scan
from . import plan009_support as support

POLICY = plan_memory_policy.PlanMemoryPolicy()

TOOL_POLICY_READ_SURFACE = (
    "has_memory_effect",
    "DEFAULT_CONFIDENCE",
    "DEFAULT_IMPORTANCE",
    "DEFAULT_MEMORY_TYPE",
    "DEFAULT_SOURCE",
    "FAILED_IMPORTANCE_FLOOR",
    "MEMORY_CONTENT_MAX_CHARS",
    "REASON_NO_POLICY_ROW",
    "REASON_POLICY_DECLINED",
    "REASON_POLICY_DEPOSIT",
)

FORBIDDEN_TOOL_POLICY_WRITE_SURFACE = (
    "to_candidates",
    "classify",
    "BOUNDARY_TABLE",
    "BOUNDARY_PREFIX_TABLE",
    "DEPOSIT_SKIP",
    "ToolMemoryPolicy",
)


def _record(action_type: str = "create_reminder", **overrides) -> support.ActionRecord:
    return support.tool_record(action_type=action_type, **overrides)


class TestToolSideDepositIsNotOverridden:
    """I4 / S5：三条工具（沉淀 / 读类强制不沉淀 / skip）逐条按 V2.4.0 边界表判定。"""

    def test_reminder_create_still_deposits_one_regardless_of_plan_membership(self):
        """§4.2.3 第 1 行 + S5：步骤成功 → 沉淀一条（**与它在不在计划里无关**）。"""
        tool_policy = tool_memory_policy.get_tool_memory_policy()
        plan_scoped = _record(dedupe_key=support.dedupe_key(), tool_id=support.REMINDER_CREATE)

        candidates = tool_policy.to_candidates(plan_scoped)

        assert len(candidates) == 1
        assert candidates[0].importance == 0.7
        assert candidates[0].source == "user_derived"
        assert candidates[0].type == "important_event"
        assert tool_memory_policy.BOUNDARY_TABLE[support.REMINDER_CREATE]["deposit"] is True

    def test_env_query_never_deposits_even_when_configured_to_deposit(self):
        """§4.2.3 第 2 行 + §8 Step 5.2：读类工具强制不沉淀（配置不可绕过硬纪律①）。"""
        rows = {
            support.ENV_QUERY: {
                "deposit": True,
                "memory_type": "important_event",
                "importance": 0.9,
                "source": "user_derived",
            }
        }
        tool_policy = tool_memory_policy.ToolMemoryPolicy(rows=rows)
        declaration = support.read_only_definition(support.ENV_QUERY)

        decision = tool_policy.classify(
            _record("query_environment", tool_id=support.ENV_QUERY), declaration
        )

        assert decision.deposit is False
        assert decision.reason == tool_memory_policy.REASON_READ_ONLY
        assert (
            tool_policy.to_candidates(
                _record("query_environment", tool_id=support.ENV_QUERY), declaration
            )
            == []
        )
        assert tool_memory_policy.BOUNDARY_TABLE[support.ENV_QUERY] == {"deposit": False}

    def test_memory_save_still_skips_to_avoid_double_delivery(self):
        """§4.2.3 第 3 行 + §8 Step 5.3：`builtin.memory.save` 仍 `skip`（避免二次投递）。"""
        tool_policy = tool_memory_policy.get_tool_memory_policy()

        decision = tool_policy.classify(
            _record("remember_fact", tool_id=support.MEMORY_SAVE)
        )

        assert decision.deposit == tool_memory_policy.DEPOSIT_SKIP
        assert decision.reason == tool_memory_policy.REASON_POLICY_SKIP
        assert tool_policy.to_candidates(
            _record("remember_fact", tool_id=support.MEMORY_SAVE)
        ) == []
        assert tool_memory_policy.BOUNDARY_TABLE[support.MEMORY_SAVE]["deposit"] == (
            tool_memory_policy.DEPOSIT_SKIP
        )

    def test_tool_boundary_table_and_templates_are_frozen(self):
        """I7：工具侧边界表与模板未被本任务触碰（值逐条冻结）。"""
        from app.character.asuna.tool import TOOL_MEMORY_TEMPLATES

        assert tool_memory_policy.BOUNDARY_TABLE == {
            "builtin.reminder.create": {
                "deposit": True,
                "memory_type": "important_event",
                "importance": 0.7,
                "source": "user_derived",
            },
            "builtin.reminder.cancel": {
                "deposit": True,
                "memory_type": "important_event",
                "importance": 0.5,
                "source": "user_derived",
            },
            "builtin.memory.save": {"deposit": "skip", "source": "user_stated"},
            "world.object.create": {
                "deposit": True,
                "memory_type": "user_preference",
                "importance": 0.5,
                "source": "user_derived",
            },
            "world.object.move": {"deposit": False},
            "world.object.use": {"deposit": False},
            "world.env.query": {"deposit": False},
            "builtin.search.query": {"deposit": False},
            "builtin.notification.send": {
                "deposit": True,
                "memory_type": "important_event",
                "importance": 0.6,
                "source": "ai_inferred",
            },
            "channel.feishu.send": {
                "deposit": True,
                "memory_type": "important_event",
                "importance": 0.6,
                "source": "ai_inferred",
            },
        }
        assert TOOL_MEMORY_TEMPLATES == {
            "builtin.reminder.create": "用户请我提醒：{content}",
            "builtin.reminder.cancel": "用户不想再被提醒：{target}",
            "builtin.memory.save": "用户告诉我：{fact}",
            "world.object.create": "用户请我准备：{object}",
            "builtin.notification.send": "我主动提醒了用户：{content}",
            "channel.feishu.send": "我主动给用户发了消息：{content}",
        }


class TestPlanningAddsNoToolBoundaryTable:
    """§8 Step 5.4：Planning 未新增工具记忆边界表（静态）。"""

    def test_no_tool_id_shaped_dict_keys_anywhere_in_the_package(self):
        offenders = {
            path.name: sorted(
                key for key in support.dict_keys(path) if "." in key
            )
            for path in support.plan_modules()
        }
        assert {name: keys for name, keys in offenders.items() if keys} == {}

    def test_tool_boundary_assets_are_never_assigned_in_the_package(self):
        for path in support.plan_modules():
            names = support.assigned_names(path)
            assert names & {
                "BOUNDARY_TABLE",
                "BOUNDARY_PREFIX_TABLE",
                "TOOL_MEMORY_TEMPLATES",
                "DEPOSIT_SKIP",
            } == set(), path.name

    def test_planning_only_reads_the_tool_memory_policy_surface(self):
        """本层对工具记忆策略的触达面 ⊆ `has_memory_effect` + 复用常量（零覆盖决策）。"""
        touched: set[str] = set()
        for path in support.plan_modules():
            touched |= scan.called_attributes(path, "tool_memory_policy")
            touched |= scan.import_from_names(path).get(
                "app.services.tool.memory_policy", set()
            )
        assert touched <= set(TOOL_POLICY_READ_SURFACE) | {
            "REASON_POLICY_DEPOSIT",
            "MEMORY_CONTENT_MAX_CHARS",
        }
        assert touched & set(FORBIDDEN_TOOL_POLICY_WRITE_SURFACE) == set()

    def test_the_two_layers_stay_orthogonal_by_construction(self):
        """判据 B 只管「计划整体」，判据 C 的权威仍在工具侧：两者的取值域零交叠。"""
        plan_keys = set(plan_memory_policy.PLAN_MEMORY_BOUNDARY_TABLE)
        tool_keys = set(tool_memory_policy.BOUNDARY_TABLE)
        assert plan_keys & tool_keys == set()
        assert all("." not in key for key in plan_keys)
        assert all("." in key for key in tool_keys)


class TestStepEventsNeverReachMemory:
    """I1 / S4：中间步骤（含成功）零写入 `memories`——本层为步骤事件产不出候选。"""

    @pytest.mark.parametrize(
        "event_kind",
        ("step_succeeded", "step_failed", "plan_created", "plan_revised"),
    )
    def test_step_and_plan_body_events_produce_no_candidate(self, event_kind, monkeypatch):
        calls = support.install_ingest_stub(monkeypatch)
        assert (
            plan_memory_policy.build_candidate(support.goal(), support.plan(), event_kind)
            is None
        )
        assert calls == []

    def test_only_the_three_terminal_outcomes_can_reach_the_memory_channel(self):
        from app.services.planning import observer as observer_mod

        assert set(observer_mod.TERMINAL_MEMORY_EVENTS) == {
            "completed",
            "failed",
            "abandoned",
        }
        assert (
            observer_mod.deliver_goal_terminal_memory(
                support.goal(), support.plan(), "skipped"
            )
            is None
        )


class TestWorldAndPlanMemoryChannelsStayIndependent:
    """I9：终态记忆与「世界事件 → 记忆」是两条独立通道（零交叉调用）。"""

    def test_world_event_ingest_is_never_reached_from_planning(self):
        for path in support.plan_modules():
            assert "ingest_from_world_event" not in path.read_text(encoding="utf-8"), path.name

    def test_the_only_ingest_entry_point_used_is_the_goal_completion_one(self):
        touched: set[str] = set()
        for path in support.plan_modules():
            touched |= scan.import_from_names(path).get("app.services.memory.ingest", set())
            touched |= scan.called_attributes(path, "memory_ingest")
        assert touched == {"ingest_from_goal_completion"}

    def test_memory_package_is_not_modified_for_this_task(self):
        """I6 半边：`memory` 零改动——本层只用既有函数（导入面与调用面逐条列举）。"""
        imports: dict[str, set[str]] = {}
        for path in support.plan_modules():
            names = scan.import_from_names(path)
            subset = {
                module: sorted(members)
                for module, members in names.items()
                if module == "app.services.memory"
                or module.startswith("app.services.memory.")
            }
            if subset:
                imports[path.name] = subset
        assert imports == {
            "context.py": {"app.services.memory": ["retriever"]},
            "memory_policy.py": {"app.services.memory": ["commands", "ingest"]},
        }
        module = support.module_path("memory_policy.py")
        assert scan.called_attributes(module, "memory_ingest") == {
            "ingest_from_goal_completion"
        }
        assert scan.called_attributes(module, "memory_commands") <= {
            "detect_command",
            "ACTION_FORGET",
        }
