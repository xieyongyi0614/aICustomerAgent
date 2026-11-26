"""PLAN-001 静态面回归：`app/services/planning/` 零 prompt / LLM / 链条面。

原「规划 prompt 逐字节不变」冻结摘要断言已删除（prompt 随能力白名单常态化演进，
冻结快照只产生假红）；`FROZEN_PROMPT_DIGEST` / `_digest` 保留供同目录其他用例复用。

原「既有自治 Flag 全 off 时 Goal 域四入口返回 `flag_disabled` 短路」两条用例已随
`vXX_` 开关体系删除而移除——`v2_autonomy_advanced_enabled` 等字段不再存在，
四入口改为常开执行，`flag_disabled` 短路路径已不存在。
"""

import hashlib
import json

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
