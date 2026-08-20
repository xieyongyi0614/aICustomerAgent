from app.chains.summary_chain import summarize
from app.core.settings import get_settings
from app.repositories import summary_repository as repo


def should_summarize(message_count: int) -> bool:
    return message_count >= get_settings().summary_threshold


async def generate(old_summary: str, new_messages: list[str]) -> str:
    if not new_messages:
        return old_summary
    new_block = "\n".join(new_messages)
    return await summarize(old_summary, new_block)


async def update(conv_id: str, new_messages: list[str]) -> None:
    if not new_messages:
        return
    current = repo.get_summary(conv_id)
    old_summary = current.summary if current else ""
    new_summary = await generate(old_summary, new_messages)
    repo.upsert_summary(conv_id, new_summary)
