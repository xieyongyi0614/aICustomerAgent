import logging

from langchain_core.runnables import Runnable

from app.chains.structured import build_structured_chain
from app.core.settings import get_settings
from app.models.scene import SceneIntentResult
from app.prompts.scene_intent import scene_intent_prompt

logger = logging.getLogger(__name__)


def build_chain(llm=None) -> Runnable:
    return build_structured_chain(
        [
            ("system", scene_intent_prompt),
            ("user", "{user_message}"),
        ],
        SceneIntentResult,
        llm,
    )


def _degraded(reason: str) -> SceneIntentResult:
    return SceneIntentResult(intent="chat", confidence=0.0, reason=reason)


async def classify(user_message: str, llm=None) -> SceneIntentResult:
    threshold = get_settings().scene_intent_threshold
    chain = build_chain(llm)
    try:
        result = await chain.ainvoke({"user_message": user_message})
    except Exception:
        logger.exception("场景意图识别失败，降级为 chat")
        return _degraded("scene_intent_failed")

    if isinstance(result, dict):
        try:
            result = SceneIntentResult.model_validate(result)
        except Exception:
            logger.warning("场景意图输出非法，降级为 chat")
            return _degraded("invalid_output")

    if result is None or result.confidence < threshold:
        return _degraded("low_confidence")
    return result
