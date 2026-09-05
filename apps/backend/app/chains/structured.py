import json
import re

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import ValidationError

from app.core.llm_factory import get_llm
from app.services.observability.llm_capture import observe_structured_chain

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _unwrap_json(text: str):
    data = json.loads(text)
    if isinstance(data, list):
        data = data[0] if data else {}
    return data


def _extract_json_text(content: str) -> str:
    match = _FENCE_RE.search(content)
    candidate = match.group(1) if match else content
    stripped = candidate.strip()
    if stripped.startswith("["):
        return stripped
    start, end = candidate.find("{"), candidate.rfind("}")
    if 0 <= start < end:
        return candidate[start : end + 1]
    return stripped


def _tolerant_schema(schema: type) -> type:
    class _Tolerant(schema):
        @classmethod
        def model_validate_json(cls, json_data, **kwargs):
            try:
                return super().model_validate_json(json_data, **kwargs)
            except ValidationError:
                return cls.model_validate(_unwrap_json(json_data))

    _Tolerant.__name__ = schema.__name__
    return _Tolerant


def build_structured_chain(
    messages: list[tuple], schema: type, llm=None
) -> Runnable:
    model = llm or get_llm()
    prompt = ChatPromptTemplate.from_messages(list(messages))
    primary = prompt | model.with_structured_output(_tolerant_schema(schema))

    parser = PydanticOutputParser(pydantic_object=schema)
    instructions = (
        parser.get_format_instructions().replace("{", "{{").replace("}", "}}")
    )
    fallback_prompt = ChatPromptTemplate.from_messages(
        [*messages, ("system", instructions)]
    )

    def _parse(message):
        text = getattr(message, "content", "") or ""
        candidate = _extract_json_text(str(text))
        try:
            return schema.model_validate_json(candidate)
        except ValidationError:
            return schema.model_validate(_unwrap_json(candidate))

    fallback = fallback_prompt | model | RunnableLambda(_parse)
    return observe_structured_chain(primary.with_fallbacks([fallback]), prompt, schema, model)