"""PLAN-001 Step 6：Flag 回归（零新增 Flag / 零 prompt 差异 / 静态面无污染）。

本任务不新增任何 Flag，也不触碰任何 prompt 面；用例把这两条写成可判定断言：

1. 规划 prompt 逐字节不变（以「捕获入参 prompt + 摘要冻结」证明零差异）。
2. `app/services/planning/` 零 prompt / LLM / 链条面（静态）。

原「既有自治 Flag 全 off 时 Goal 域四入口返回 `flag_disabled` 短路」两条用例已随
`vXX_` 开关体系删除而移除——`v2_autonomy_advanced_enabled` 等字段不再存在，
四入口改为常开执行，`flag_disabled` 短路路径已不存在。
"""

import hashlib
import json

from app.services.goal import planning as goal_planning

from . import _plan_scan as scan

FROZEN_PROMPT_DIGEST = (
    "da49e6e6be0233301af50a10cb5e7b3764e539625a6817d3e28167aa39f2c818"
)

PROMPT_SURFACE_TOKENS = (
    "_build_messages",
    "build_structured_chain",
    "ChatPromptTemplate",
    "HumanMessage",
    "SystemMessage",
    "llm_gateway",
    "get_llm",
)

PLANNING_FORBIDDEN_IMPORT_PREFIXES = (
    "app.chains",
    "langchain",
    "app.core.llm_factory",
)


def _digest(messages: list) -> str:
    payload = json.dumps([list(pair) for pair in messages], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_planning_prompt_bytes_are_unchanged(make_goal, stub_planning_llm, autonomy_on):
    assert autonomy_on
    recorder: dict = {}
    stub_planning_llm(recorder=recorder)
    goal = make_goal(description="prompt 快照目标", priority=4, domain="relationship")
    assert goal_planning.plan_goal(goal.id, goal_planning.TRIGGER_CREATED)["status"] == "ok"
    messages = recorder["messages"]
    assert [pair[0] for pair in messages] == ["system", "human"]
    assert _digest(messages) == FROZEN_PROMPT_DIGEST
    assert "action_succeeded" in messages[0][1]
    assert "threshold_reached" in messages[0][1]
    assert json.loads(messages[1][1])["goal"]["priority"] == 4


def test_planning_package_has_no_prompt_or_llm_surface():
    offenders = {}
    for path in scan.planning_modules():
        hits = scan.code_violations(path, PROMPT_SURFACE_TOKENS)
        imports = sorted(
            module
            for module in scan.imported_modules(path)
            for prefix in PLANNING_FORBIDDEN_IMPORT_PREFIXES
            if module == prefix or module.startswith(prefix + ".")
        )
        if hits or imports:
            offenders[scan.module_name(path)] = {"tokens": hits, "imports": imports}
    assert not offenders
