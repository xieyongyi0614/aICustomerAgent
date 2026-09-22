from __future__ import annotations

import logging
from datetime import datetime

from app.services.governance.models import DeletionReport
from app.services.governance.registry import all_handlers

logger = logging.getLogger(__name__)


def delete_user_data(user_id: str, *, now: datetime | None = None) -> DeletionReport:
    timestamp = now or datetime.now()
    per_domain: dict[str, int] = {}
    failed: list[str] = []
    for handlers in all_handlers():
        try:
            per_domain[handlers.name] = int(handlers.delete(user_id))
        except Exception:
            logger.exception("治理删除失败 domain=%s user=%s", handlers.name, user_id)
            failed.append(handlers.name)
    return DeletionReport(
        user_id=user_id,
        deleted_at=timestamp,
        per_domain=per_domain,
        total=sum(per_domain.values()),
        failed_domains=tuple(failed),
    )
