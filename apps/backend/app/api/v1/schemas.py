from pydantic import BaseModel


class ChatRequest(BaseModel):
    session_id: str | None = None
    content: str


class ChatSessionResponse(BaseModel):
    session_id: str


class ChatDelta(BaseModel):
    delta: str


class ChatDone(BaseModel):
    done: bool = True
