import argparse

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.core.db import (
    Conversation,
    ConversationSummary,
    Memory,
    Message,
    SceneStateRow,
)
from app.core.settings import get_settings

MIGRATION_ORDER = (Conversation, Message, ConversationSummary, Memory, SceneStateRow)

LEGACY_MEMORY_KEY_MAP = {"memory": "content", "memory_type": "type"}


def _source_rows(source_session, model):
    if model is not Memory:
        return source_session.query(model).all()
    columns = {
        column["name"]
        for column in inspect(source_session.bind).get_columns("memories")
    }
    if "content" in columns:
        return source_session.query(Memory).all()
    rows = source_session.execute(text("SELECT * FROM memories")).mappings()
    return [
        Memory(**{LEGACY_MEMORY_KEY_MAP.get(key, key): value for key, value in row.items()})
        for row in rows
    ]


def _create_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


def migrate(source_url: str, target_url: str | None = None) -> dict[str, int]:
    target = _create_engine(target_url or get_settings().database_url)
    source = _create_engine(source_url)
    counts: dict[str, int] = {}
    with Session(source) as source_session, Session(target) as target_session:
        for model in MIGRATION_ORDER:
            rows = _source_rows(source_session, model)
            target_session.query(model).delete()
            for row in rows:
                target_session.merge(row)
            target_session.commit()
            counts[model.__tablename__] = len(rows)
    source.dispose()
    target.dispose()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="migrate sqlite data to postgresql")
    parser.add_argument("--source", default="sqlite:///./asuna.db")
    parser.add_argument("--target", default=None)
    args = parser.parse_args()
    counts = migrate(args.source, args.target)
    for table, count in counts.items():
        print(f"{table}: {count} rows")


if __name__ == "__main__":
    main()
