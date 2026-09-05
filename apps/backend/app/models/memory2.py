from pydantic import BaseModel


class EvaluationVerdict(BaseModel):
    """评估器 LLM 兜底输出；type 仅为建议，终值由代码映射规则决定。"""

    approve: bool
    type: str | None = None
    reason: str = ""
