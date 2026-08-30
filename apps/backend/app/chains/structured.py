import re

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from app.core.llm_factory import get_llm
from app.services.observability.llm_capture import observe_structured_chain

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json_text(content: str) -> str:
    match = _FENCE_RE.search(content)
    candidate = match.group(1) if match else content
    start, end = candidate.find("{"), candidate.rfind("}")
    if 0 <= start < end:
        return candidate[start : end + 1]
    return candidate.strip()


def build_structured_chain(
    messages: list[tuple], schema: type, llm=None
) -> Runnable:
    model = llm or get_llm()
    prompt = ChatPromptTemplate.from_messages(list(messages))
    primary = prompt | model.with_structured_output(schema)

    parser = PydanticOutputParser(pydantic_object=schema)
    instructions = (
        parser.get_format_instructions().replace("{", "{{").replace("}", "}}")
    )
    fallback_prompt = ChatPromptTemplate.from_messages(
        [*messages, ("system", instructions)]
    )

    def _parse(message):
        text = getattr(message, "content", "") or ""
        return schema.model_validate_json(_extract_json_text(str(text)))

    fallback = fallback_prompt | model | RunnableLambda(_parse)
    return observe_structured_chain(primary.with_fallbacks([fallback]), prompt, schema, model)