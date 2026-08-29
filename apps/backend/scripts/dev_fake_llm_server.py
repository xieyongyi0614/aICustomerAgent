import os
import sys

os.environ.setdefault("OPENAI_API_KEY", "test")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn

from app.api.v1.deps import get_chat_llm
from app.main import app
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda


class FakeLLM(BaseChatModel):
    """开发用假 LLM：本地回放固定响应，不产生任何真实调用。"""

    response: object = ""
    structured_responses: dict = {}

    def __init__(self, response="", structured_responses=None, **kwargs):
        super().__init__(**kwargs)
        self.response = response
        self.structured_responses = structured_responses or {}

    def with_structured_output(self, schema, **kwargs):
        def _resolve(_inputs):
            data = self.structured_responses.get(schema.__name__)
            if isinstance(data, dict):
                return schema.model_validate(data)
            return data

        return RunnableLambda(_resolve)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        text = self.response if isinstance(self.response, str) else "".join(self.response)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        chunks = self.response if isinstance(self.response, list) else [self.response]
        for chunk in chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=chunk))

    @property
    def _llm_type(self):
        return "fake"

llm = FakeLLM(
    response=["好的", "，我先记下了。"],
    structured_responses={
        "RoleMode": {
            "mode": "immersive",
            "intent": "emotional",
            "confidence": 0.2,
            "reason": "fake 低置信示例",
        },
        "TurnAnalysis": {
            "user_emotion": {"emotion": "sad", "event": "setback"},
            "behavior": {"behavior": "comfort", "reason": "先接住情绪"},
        },
        "StateUpdateDecision": {
            "mood": "worried",
            "mood_reason": "用户压力较大",
            "inner_state": "担心用户熬夜赶工",
            "current_topic": "用户的调试控制台项目",
        },
        "MemoryDecision": {
            "should_save": True,
            "memory": "用户正在开发 Character Agent Debug Console",
            "memory_type": "goal",
            "importance": 0.85,
        },
    },
)

app.dependency_overrides[get_chat_llm] = lambda: llm

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
