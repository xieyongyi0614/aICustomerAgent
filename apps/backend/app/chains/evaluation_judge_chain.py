"""V7.5 LLM Judge 链（llm-judge.md）：单次合并调用 + 一层降级 + evidence 自证清理。

失败契约：任何异常返回 None，由引擎降级为规则版报告。
"""

import logging
import time

from langchain_core.runnables import Runnable

from app.chains.structured import build_structured_chain
from app.core.llm_factory import get_llm
from app.core.settings import get_settings
from app.models.evaluation_judge import ProactiveJudgeResult, TurnJudgeResult
from app.prompts.evaluation_judge import build_evaluation_judge_messages

logger = logging.getLogger(__name__)


def _sanitize_evidence(judgement, reply: str):
    """evidence 非 reply 子串 → 清空（引擎侧降级为无证据 issue）。"""
    if judgement is None:
        return judgement
    quote = judgement.evidence_quote
    if quote and quote not in (reply or ""):
        judgement = judgement.model_copy(update={"evidence_quote": ""})
    return judgement


def _restrict_memory_ids(memory_judgement, allowed_ids: set[str]):
    if memory_judgement is None:
        return memory_judgement
    filtered = [mid for mid in memory_judgement.memory_ids if mid in allowed_ids]
    if filtered != list(memory_judgement.memory_ids):
        return memory_judgement.model_copy(update={"memory_ids": filtered})
    return memory_judgement


async def _run(schema, digest: dict, character_id: str, subject: str, llm, trace, step_name):
    started = time.perf_counter()
    try:
        model = llm if llm is not None else get_llm(_judge_profile_id())
        chain: Runnable = build_structured_chain(
            build_evaluation_judge_messages(digest, character_id=character_id, subject=subject),
            schema,
            model,
        )
        result = await chain.ainvoke({})
        reply = str(digest.get("reply", "") or "")
        if isinstance(result, TurnJudgeResult):
            result = result.model_copy(
                update={
                    "persona": _sanitize_evidence(result.persona, reply),
                    "emotion": _sanitize_evidence(result.emotion, reply),
                    "memory": _restrict_memory_ids(
                        _sanitize_evidence(result.memory, reply),
                        _allowed_memory_ids(digest),
                    ),
                }
            )
        elif isinstance(result, ProactiveJudgeResult):
            result = result.model_copy(
                update={
                    "persona": _sanitize_evidence(result.persona, reply),
                    "autonomy": _sanitize_evidence(result.autonomy, reply),
                }
            )
        if trace is not None:
            trace.record(
                step_name, (time.perf_counter() - started) * 1000,
                "ok",
                model=getattr(model, "model_name", None) or "",
            )
        return result
    except Exception as exc:
        logger.warning("评估 judge 失败，降级为规则版：%s", exc.__class__.__name__)
        if trace is not None:
            trace.record(
                step_name, (time.perf_counter() - started) * 1000,
                "degraded", error=exc.__class__.__name__,
            )
        return None


def _judge_profile_id() -> str | None:
    profile_id = get_settings().evaluation_judge_profile
    return profile_id or None


def _allowed_memory_ids(digest: dict) -> set[str]:
    return {
        str(memory.get("id"))
        for memory in (digest.get("injected_memories") or [])
        if isinstance(memory, dict) and memory.get("id") is not None
    }


async def judge_turn(digest: dict, character_id: str = "asuna", llm=None, trace=None):
    return await _run(
        TurnJudgeResult, digest, character_id, "turn", llm, trace, "evaluation_judge"
    )


async def judge_proactive(
    digest: dict, character_id: str = "asuna", llm=None, trace=None
):
    return await _run(
        ProactiveJudgeResult, digest, character_id, "proactive_action", llm, trace, "evaluation_judge"
    )
