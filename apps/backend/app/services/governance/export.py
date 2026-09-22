from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Mapping

from app.services.governance.models import ExportBundle
from app.services.governance.registry import all_handlers


def export_user_data(
    user_id: str,
    *,
    fmt: Literal["json", "csv"] = "json",
    now: datetime | None = None,
) -> ExportBundle:
    timestamp = now or datetime.now()
    domains: dict[str, Mapping[str, Any]] = {}
    for handlers in all_handlers():
        domains[handlers.name] = dict(handlers.export(user_id))
    return ExportBundle(
        user_id=user_id,
        generated_at=timestamp,
        domains=domains,
        format=fmt,
    )


def bundle_to_csv(bundle: ExportBundle) -> str:
    lines = ["domain,key,value"]
    for domain, payload in sorted(bundle.domains.items()):
        for key, value in sorted(payload.items(), key=lambda item: str(item[0])):
            lines.append(f"{domain},{key},{value}")
    return "\n".join(lines) + "\n"
