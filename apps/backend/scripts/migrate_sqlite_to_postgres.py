import argparse

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import Conversation, ConversationSummary, Memory, Message
from app.core.settings import get_settings

MIGRATION_ORDER = (Conversation, Message, ConversationSummary, Memory)


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
            rows = source_session.query(model).all()
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
