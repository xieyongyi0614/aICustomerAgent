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


def _strip_nulls(data):
    if isinstance(data, dict):
        return {key: _strip_nulls(value) for key, value in data.items() if value is not None}
    if isinstance(data, list):
        return [_strip_nulls(item) for item in data]
    return data


def _tolerant_schema(schema: type) -> type:
    class _Tolerant(schema):
        @classmethod
        def model_validate_json(cls, json_data, **kwargs):
            try:
                return super().model_validate_json(json_data, **kwargs)
            except ValidationError:
                return cls.model_validate(_unwrap_json(json_data))

        @classmethod
        def model_validate(cls, obj, **kwargs):
            try:
                return super().model_validate(obj, **kwargs)
            except ValidationError:
                return super().model_validate(_strip_nulls(obj))

    _Tolerant.__name__ = schema.__name__
    return _Tolerant


def build_structured_chain(
    messages: list[tuple], schema: type, llm=None
) -> Runnable:
    model = llm or get_llm()
    prompt = ChatPromptTemplate.from_messages(list(messages))
    tolerant_model = _tolerant_schema(schema)
    primary = prompt | model.with_structured_output(tolerant_model)

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
        return tolerant_model.model_validate_json(candidate)

    fallback = fallback_prompt | model | RunnableLambda(_parse)
    return observe_structured_chain(primary.with_fallbacks([fallback]), prompt, schema, model)