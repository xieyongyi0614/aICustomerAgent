"""PLAN-011 Step 6 单测：内部接口契约冻结与三条纪律的静态断言（§8.1~§8.6 / §9.2 I7 / I8 / I10）。

契约对照口径（「签名漂移即失败」）：逐模块把 architecture §8.1 ~ §8.6 的声明形参名与顺序写成
快照，与运行时 `inspect.signature` 比对；**已留痕的可选增补**单列（不是漂移，见各模块模块文档）：

| 声明 | 落地形态 | 留痕处 |
|---|---|---|
| `PlanScheduler.order(plan) -> list[int]` | `order(plan, goal=None) -> list[PlanStepSpec]`，下标形状由 `order_indexes` 提供 | `scheduler.py` 模块文档末段 |
| `PlanExecutorBridge.reconcile(outcome, step)` | `+ *, max_attempts=None` | `executor_bridge.py` |
| `PlanObserver.collect_facts(user_id, ctx)` | `+ *, observation_keys=None`（白名单三态） | `observer.py` 模块文档末段 |
| `PlanObserver.settle(...) -> PlanOutcome` | 返回 `PlanSettlement`（`PlanOutcome` 已被引擎占用） | `observer.py` 模块文档「两处实现核对」 |
| `PlanRevisionPolicy.policy_for(step)` | `+ *, max_attempts=...` | `revision.py` |
| `PlanningEngine.enqueue(..., *, ctx)` | `ctx=None` 可缺省（装配在 job 执行期发生） | `engine.py` |

三条纪律（只读 / 零 IO / 纯函数）在本文件以静态扫描判定；零新建表由「四张既有表投影 + 迁移链头」
两侧共同钉住。
"""

import ast
import inspect
import io
import tokenize
from pathlib import Path

from app.api.v1 import debug as debug_api
from app.core.db import Base
from app.repositories import goal_repository
from app.services.planning import (
    context as plan_context,
    decompose as plan_decompose,
    engine as plan_engine,
    executor_bridge as plan_bridge,
    observer as plan_observer,
    revision as plan_revision,
    revision_listener as plan_listener,
    scheduler as plan_scheduler,
)

from . import _plan_scan as scan

ENGINE_PATH = Path(plan_engine.__file__)
CONTEXT_PATH = Path(plan_context.__file__)
DECOMPOSE_PATH = Path(plan_decompose.__file__)
SCHEDULER_PATH = Path(plan_scheduler.__file__)
BRIDGE_PATH = Path(plan_bridge.__file__)
OBSERVER_PATH = Path(plan_observer.__file__)
REVISION_PATH = Path(plan_revision.__file__)
LISTENER_PATH = Path(plan_listener.__file__)
DEBUG_PATH = Path(debug_api.__file__)

PURE_MODULES = {
    "scheduler.py": SCHEDULER_PATH,
    "revision.py": REVISION_PATH,
    "decompose.py": DECOMPOSE_PATH,
}

FORBIDDEN_IO_PREFIXES = (
    "app.repositories",
    "app.application",
    "app.core.db",
    "sqlalchemy",
    "socket",
    "requests",
    "httpx",
)

PLANNED_PROJECTION_TABLES: tuple[str, ...] = (
    "action_records",
    "decision_records",
    "goal_plans",
    "loop_runs",
)
"""可观测面的**唯一**投影来源（四张既有表，§4.1.3 / §7）。"""

ALLOWED_PROJECTION_REPOSITORIES: tuple[str, ...] = (
    "action_repository",
    "decision_repository",
    "goal_repository",
    "loop_run_repository",
)

FORBIDDEN_WRITE_TOKENS: tuple[str, ...] = (
    "session.add",
    "session.commit",
    "session.delete",
    "session.merge",
    "session.flush",
    ".update(",
    ".delete(",
    "create_plan",
    "set_plan_status",
    "set_plan_rejection",
    "update_plan_progress",
    "finish_goal",
    "reactivate_goal",
    "complete_goal",
    "fail_goal",
    "set_status",
)

SIGNATURES = (
    (
        "PlanningEngine.plan",
        lambda: plan_engine.PlanningEngine.plan,
        ("self", "goal", "ctx", "trigger"),
        (),
        "PlanOutcome",
    ),
    (
        "PlanningEngine.revise",
        lambda: plan_engine.PlanningEngine.revise,
        ("self", "plan", "ctx", "reason"),
        (),
        "PlanOutcome",
    ),
    (
        "PlanningEngine.enqueue",
        lambda: plan_engine.PlanningEngine.enqueue,
        ("self", "user_id", "goal_id", "trigger", "ctx"),
        (),
        "bool",
    ),
    (
        "PlanningEngine.run_jobs",
        lambda: plan_engine.PlanningEngine.run_jobs,
        ("self",),
        (),
        "int",
    ),
    (
        "PlanningEngine.register_runtime",
        lambda: plan_engine.PlanningEngine.register_runtime,
        ("self",),
        (),
        "None",
    ),
    (
        "PlanContextAssembler.assemble",
        lambda: plan_context.PlanContextAssembler.assemble,
        ("self", "goal", "run", "now"),
        (),
        "PlanContext | PlanUnavailable",
    ),
    (
        "PlanContextProbe.world_available",
        lambda: plan_context.PlanContextProbe.world_available,
        ("self", "user_id"),
        (),
        "bool",
    ),
    (
        "PlanContextProbe.surface_size",
        lambda: plan_context.PlanContextProbe.surface_size,
        ("self", "user_id", "run_kind"),
        (),
        "int",
    ),
    (
        "PlanContextProbe.degraded_sources",
        lambda: plan_context.PlanContextProbe.degraded_sources,
        ("self", "user_id"),
        (),
        "list[str]",
    ),
    (
        "PlanScheduler.order",
        lambda: plan_scheduler.PlanScheduler.order,
        ("plan",),
        ("goal",),
        "list[PlanStepSpec]",
    ),
    (
        "PlanScheduler.current_step",
        lambda: plan_scheduler.PlanScheduler.current_step,
        ("plan",),
        (),
        "PlanStepSpec | None",
    ),
    (
        "PlanScheduler.all_done",
        lambda: plan_scheduler.PlanScheduler.all_done,
        ("plan",),
        (),
        "bool",
    ),
    (
        "PlanScheduler.has_executable",
        lambda: plan_scheduler.PlanScheduler.has_executable,
        ("plan",),
        (),
        "bool",
    ),
    (
        "PlanScheduler.ready_steps",
        lambda: plan_scheduler.PlanScheduler.ready_steps,
        ("plan",),
        (),
        "list[PlanStepSpec]",
    ),
    (
        "PlanScheduler.blocked_reason",
        lambda: plan_scheduler.PlanScheduler.blocked_reason,
        ("plan", "ctx"),
        (),
        "str | None",
    ),
    (
        "PlanExecutorBridge.to_intent",
        lambda: plan_bridge.PlanExecutorBridge.to_intent,
        ("self", "goal", "plan", "step", "ctx"),
        (),
        "ActionIntent",
    ),
    (
        "PlanExecutorBridge.execute_step",
        lambda: plan_bridge.PlanExecutorBridge.execute_step,
        ("self", "goal", "plan", "step", "ctx"),
        (),
        "PlanStepOutcome",
    ),
    (
        "PlanExecutorBridge.reconcile",
        lambda: plan_bridge.PlanExecutorBridge.reconcile,
        ("self", "outcome", "step"),
        ("max_attempts",),
        "none",
    ),
    (
        "PlanObserver.collect_facts",
        lambda: plan_observer.PlanObserver.collect_facts,
        ("self", "user_id", "ctx"),
        ("observation_keys",),
        "dict",
    ),
    (
        "PlanObserver.observe",
        lambda: plan_observer.PlanObserver.observe,
        ("self", "goal", "plan", "facts", "now"),
        (),
        "PlanAdvance",
    ),
    (
        "PlanObserver.evaluate",
        lambda: plan_observer.PlanObserver.evaluate,
        ("criteria", "facts"),
        (),
        "bool | None",
    ),
    (
        "PlanObserver.settle",
        lambda: plan_observer.PlanObserver.settle,
        ("self", "goal", "plan", "advance"),
        (),
        "PlanSettlement",
    ),
    (
        "PlanRevisionPolicy.should_replan",
        lambda: plan_revision.PlanRevisionPolicy.should_replan,
        ("self", "outcome", "plan", "ctx"),
        (),
        "str | None",
    ),
    (
        "PlanRevisionPolicy.policy_for",
        lambda: plan_revision.PlanRevisionPolicy.policy_for,
        ("step",),
        ("max_attempts",),
        "RetryPolicy",
    ),
    (
        "PlanRevisionPolicy.explain",
        lambda: plan_revision.PlanRevisionPolicy.explain,
        ("self", "plan", "reason"),
        (),
        "dict",
    ),
    (
        "PlanValidator.validate_shape",
        lambda: plan_decompose.PlanValidator.validate_shape,
        ("steps", "max_depth"),
        (),
        "list[str]",
    ),
    (
        "PlanValidator.validate_binding",
        lambda: plan_decompose.PlanValidator.validate_binding,
        ("steps", "surface"),
        (),
        "list[str]",
    ),
    (
        "PlanValidator.validate_budget",
        lambda: plan_decompose.PlanValidator.validate_budget,
        ("steps", "plan_versions", "budget"),
        (),
        "list[str]",
    ),
    (
        "PlanningRevisionListener.on_insight_created",
        lambda: plan_listener.PlanningRevisionListener.on_insight_created,
        ("self", "user_id", "created"),
        (),
        "None",
    ),
    (
        "PlanningRevisionListener.enqueue_replan",
        lambda: plan_listener.PlanningRevisionListener.enqueue_replan,
        ("self", "goal_id", "insight_id"),
        (),
        "bool",
    ),
)

REPOSITORY_CONTRACT = (
    ("create_plan", ("record",)),
    ("get_plan", ("plan_id",)),
    ("get_latest_plan", ("goal_id",)),
    ("list_plans", ("goal_id",)),
    ("count_plans", ("goal_id",)),
    ("set_plan_status", ("plan_id", "status")),
    ("set_plan_rejection", ("plan_id", "reason")),
    ("update_plan_progress", ("plan_id", "sub_goals")),
    ("list_active_plans", ("user_id",)),
    ("list_plans_by_status", ("user_id", "statuses")),
    ("count_plan_versions", ("goal_id",)),
    ("list_terminal_plans_since", ("user_id", "since")),
)

KEYWORD_ONLY_DECLARED = {
    "PlanningEngine.plan": ("trigger",),
    "PlanningEngine.revise": ("reason",),
    "PlanContextAssembler.assemble": ("run", "now"),
    "PlanContextProbe.surface_size": ("run_kind",),
    "PlanObserver.observe": ("now",),
    "PlanExecutorBridge.reconcile": ("max_attempts",),
    "PlanObserver.collect_facts": ("observation_keys",),
    "PlanRevisionPolicy.policy_for": ("max_attempts",),
    "PlanValidator.validate_shape": ("max_depth",),
}

OPTIONAL_DECLARED = {
    "PlanningEngine.enqueue": ("ctx",),
    "PlanContextAssembler.assemble": ("run", "now"),
}
"""声明面内的可缺省形参（架构记法未标默认值，落地为 `None`；形状与语义均未变）。"""


def _code_text(source: str) -> str:
    """经 `tokenize` 丢弃注释与字符串后的紧凑可执行文本（与 `_plan_scan` 同口径）。"""
    return "".join(
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    )


def _plan_section_source() -> str:
    """计划面段落（`_plan_debug_enabled` 门控已随 v25 去门控删除，锚点前移至 `_plan_statuses`）。"""
    source = DEBUG_PATH.read_text(encoding="utf-8")
    marker = "def _plan_statuses"
    return source[source.index(marker) :]


def _plan_section_tree() -> ast.Module:
    return ast.parse(_plan_section_source())


def _return_text(func) -> str:
    annotation = inspect.signature(func).return_annotation
    if annotation is inspect.Parameter.empty:
        return "none"
    return annotation if isinstance(annotation, str) else getattr(annotation, "__name__", str(annotation))


class TestInterfaceFreeze:
    """U1：六个模块公开签名与 architecture §8.1 ~ §8.6 逐条一致。"""

    def test_every_declared_signature_is_unchanged(self):
        for label, resolve, declared, documented_optional, declared_return in SIGNATURES:
            func = resolve()
            parameters = dict(inspect.signature(func).parameters)
            assert tuple(parameters) == declared + documented_optional, label
            for name in declared:
                if name in OPTIONAL_DECLARED.get(label, ()):
                    assert parameters[name].default is not inspect.Parameter.empty, (label, name)
                    continue
                assert parameters[name].default is inspect.Parameter.empty, (label, name)
            for name in documented_optional:
                assert parameters[name].default is not inspect.Parameter.empty, (label, name)
            assert _return_text(func) == declared_return, label

    def test_declared_keyword_only_parameters_stay_keyword_only(self):
        for label, resolve, _, _, _ in SIGNATURES:
            func = resolve()
            parameters = dict(inspect.signature(func).parameters)
            for name in KEYWORD_ONLY_DECLARED.get(label, ()):
                assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY, (label, name)

    def test_pure_classes_expose_no_extra_public_methods(self):
        """公开面闭合：新增公开方法即契约扩张（本任务冻结期不允许静默扩张）。"""
        expected = {
            plan_engine.PlanningEngine: {
                "plan",
                "revise",
                "enqueue",
                "run_jobs",
                "register_runtime",
            },
            plan_context.PlanContextAssembler: {"assemble"},
            plan_context.PlanContextProbe: {
                "world_available",
                "surface_size",
                "degraded_sources",
            },
            plan_scheduler.PlanScheduler: {
                "order",
                "order_indexes",
                "current_step",
                "all_done",
                "has_executable",
                "ready_steps",
                "blocked_reason",
                "propagate_failure",
            },
            plan_bridge.PlanExecutorBridge: {
                "to_intent",
                "execute_step",
                "reconcile",
            },
            plan_observer.PlanObserver: {
                "collect_facts",
                "evaluate",
                "observe",
                "settle",
                "observe_user_goals",
            },
            plan_revision.PlanRevisionPolicy: {
                "should_replan",
                "policy_for",
                "kept_steps",
                "dropped_steps",
                "budget_exhausted",
                "explain",
            },
            plan_decompose.PlanValidator: {
                "validate_shape",
                "validate_binding",
                "validate_budget",
            },
            plan_listener.PlanningRevisionListener: {
                "on_insight_created",
                "enqueue_replan",
                "mappable_goal_id",
                "evidence_refs_for",
                "reset",
            },
        }
        for owner, names in expected.items():
            public = {
                name
                for name in vars(owner)
                if not name.startswith("_") and callable(getattr(owner, name))
            }
            assert public == names, owner.__name__

    def test_value_object_field_snapshots_are_unchanged(self):
        import dataclasses

        assert tuple(field.name for field in dataclasses.fields(plan_engine.PlanOutcome)) == (
            "status",
            "plan",
            "rejection_reason",
            "steps",
            "degraded",
        )
        assert tuple(plan_observer.PlanSettlement.__dataclass_fields__) == (
            "decision",
            "goal_status",
            "transitioned",
            "reason",
        )
        from app.models.plan import PlanAdvance, PlanRevision

        assert tuple(PlanAdvance.model_fields) == (
            "goal_id",
            "plan_id",
            "plan_version",
            "decision",
            "reason",
            "at",
            "step_index",
            "facts_digest",
        )
        assert tuple(PlanRevision.model_fields) == (
            "from_version",
            "to_version",
            "reason",
            "trigger_source",
            "at",
            "evidence_refs",
            "kept_steps",
        )

    def test_plan_repository_face_is_the_declared_twelve(self):
        from app.models.goal import PLAN_STATUS_VALUES

        for name, declared in REPOSITORY_CONTRACT:
            assert tuple(inspect.signature(getattr(goal_repository, name)).parameters) == declared, name
        assert len(REPOSITORY_CONTRACT) == 12
        assert set(PLAN_STATUS_VALUES) == {
            "draft",
            "validated",
            "active",
            "rejected",
            "superseded",
        }


class TestThreeDisciplines:
    """I8：只读 / 零 IO / 纯函数三条纪律各有静态断言。"""

    def test_pure_modules_have_no_io_surface(self):
        for name, path in PURE_MODULES.items():
            offenders = [
                module
                for module in scan.imported_modules(path)
                for prefix in FORBIDDEN_IO_PREFIXES
                if module == prefix or module.startswith(prefix + ".")
            ]
            assert offenders == [], (name, offenders)

    def test_pure_modules_never_read_settings_or_repositories(self):
        for name, path in PURE_MODULES.items():
            executables = {
                node.func.id
                for node in scan.call_nodes(path)
                if hasattr(node.func, "id")
            }
            assert "get_settings" not in executables, name
            assert not scan.goal_repository_call_names(path), name

    def test_pure_modules_are_reproducible_for_the_same_input(self, db_session_factory, make_goal):
        """同输入同输出：同一 plan 连续两次调用的输出逐条相等（可复现锚点）。"""
        from app.models.goal import GoalPlanRecord, SubGoalSpec

        from . import plan011_support as support

        goal = make_goal(user_id=support.USER, description="可复现")
        plan = GoalPlanRecord(
            goal_id=goal.id,
            version=1,
            status="active",
            sub_goals=[
                SubGoalSpec.model_validate(support.step_spec(1)),
                SubGoalSpec.model_validate(support.step_spec(2, depends_on=[1])),
            ],
            created_at=support.NOW,
            updated_at=support.NOW,
        )
        for call in (
            lambda: plan_scheduler.PlanScheduler.order_indexes(plan),
            lambda: plan_scheduler.PlanScheduler.ready_steps(plan),
            lambda: plan_scheduler.PlanScheduler.all_done(plan),
            lambda: plan_scheduler.PlanScheduler.has_executable(plan),
            lambda: plan_scheduler.PlanScheduler.blocked_reason(plan, None),
            lambda: plan_decompose.PlanValidator.validate_shape(plan.sub_goals, max_depth=2),
            lambda: plan_decompose.PlanValidator.validate_binding(plan.sub_goals, None),
            lambda: plan_revision.PlanRevisionPolicy().explain(plan, "step_attempt_exhausted"),
        ):
            first = call()
            for _ in range(2):
                assert call() == first
        plan_advance = plan_revision.PlanRevisionPolicy()
        assert plan_advance.policy_for(plan.sub_goals[0]) == plan_advance.policy_for(
            plan.sub_goals[0]
        )

    def test_observer_observe_takes_facts_from_the_caller(self):
        source = OBSERVER_PATH.read_text(encoding="utf-8")
        body = source.split("def observe(", 1)[1].split("def settle(", 1)[0]
        code = _code_text(body)
        for token in ("collect_facts", "goal_repository", "action_repository", "get_settings"):
            assert token not in code, token

    def test_context_assembler_is_io_only_inside_assemble(self):
        source = CONTEXT_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        assembler = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PlanContextAssembler"
        )
        probe = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PlanContextProbe"
        )
        assertions = (
            (assembler, {"assemble", "_build_context", "_assemble_tool_surface"}),
            (
                probe,
                {
                    "__init__",
                    "_snapshot",
                    "world_available",
                    "surface_size",
                    "degraded_sources",
                },
            ),
        )
        for klass, expected_methods in assertions:
            methods = {
                node.name for node in klass.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            }
            assert methods == expected_methods, klass.name
        probe_code = _code_text(ast.unparse(probe))
        for token in ("goal_repository", "get_settings", "SessionLocal", "world_engine"):
            assert token not in probe_code, token
        helper_code = _code_text(
            ast.unparse(
                [node for node in assembler.body if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)]
            )
        )
        for token in ("session.add", "session.commit", "create_plan", "set_plan_status"):
            assert token not in helper_code, token


class TestDebugSurfaceDiscipline:
    """D9 / D10 / I7 / I10：调试端点只读、只投影四张既有表、零新建表。"""

    def test_every_plan_endpoint_is_a_read_only_get(self):
        plan_routes = [
            route
            for route in debug_api.debug_router.routes
            if route.path.startswith("/debug/plans")
        ]
        assert len(plan_routes) == 6
        for route in plan_routes:
            assert route.methods == {"GET"}, route.path

    def test_plan_section_contains_no_write_call(self):
        code = _code_text(_plan_section_source())
        offenders = [token for token in FORBIDDEN_WRITE_TOKENS if token in code]
        assert offenders == []

    def test_plan_section_touches_only_the_four_projection_repositories(self):
        found = {
            node.value.id
            for node in ast.walk(_plan_section_tree())
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id.endswith("_repository")
        }
        assert found <= set(ALLOWED_PROJECTION_REPOSITORIES)
        assert found == {"goal_repository", "decision_repository"}

    def test_plan_section_references_no_orm_row_or_session(self):
        code = _code_text(_plan_section_source())
        for token in (
            "GoalPlanRow",
            "GoalRow",
            "DecisionRecordRow",
            "LoopRunRow",
            "ActionRecordRow",
            "SessionLocal",
            "mapped_column",
        ):
            assert token not in code, token

    def test_debug_module_defines_no_orm_table(self):
        source = DEBUG_PATH.read_text(encoding="utf-8")
        code = _code_text(source)
        assert "mapped_column" not in code
        assert "SessionLocal" not in code
        assert "app.core.db" not in "".join(scan.imported_modules(DEBUG_PATH))

    def test_projection_tables_are_the_four_existing_ones(self):
        tables = set(Base.metadata.tables)
        for table in PLANNED_PROJECTION_TABLES:
            assert table in tables, table
        assert "plan_debug_projection" not in tables

    def test_migration_chain_head_is_still_0051(self):
        import re

        versions = Path(goal_repository.__file__).parents[2] / "migrations" / "versions"
        numbered = sorted(
            int(match.group(1))
            for path in versions.glob("*.py")
            if (match := re.match(r"(\d+)_", path.name))
        )
        assert max(numbered) == 51
        assert f"{max(numbered):04d}" == "0051"
