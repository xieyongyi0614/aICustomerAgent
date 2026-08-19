from datetime import datetime

from pydantic import BaseModel


class ConversationSummary(BaseModel):
    conversation_id: str
    summary: str
    updated_at: datetime
