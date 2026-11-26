"""治理域核心：领域处理器模型、注册表、删除 / 导出 / 溯源。

由 models / registry / provenance / delete / export 五文件合并归位
（services 归位批次 3，2026-09-30）；prompt_guard 独立零耦合，单独留文件。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal, Mapping
from app.core import timeutil

DomainExportHandler = Callable[[str], Mapping[str, Any]]
DomainDeleteHandler = Callable[[str], int]
DomainProvenanceReader = Callable[[str, str], "ProvenanceRef | None"]


@dataclass(frozen=True, slots=True)
class ProvenanceRef:
    domain: str
    record_id: str
    source: str
    source_ref: str


@dataclass(frozen=True, slots=True)
class DomainHandlers:
    name: str
    export: DomainExportHandler
    delete: DomainDeleteHandler
    provenance: DomainProvenanceReader | None = None


@dataclass(frozen=True, slots=True)
class ExportBundle:
    user_id: str
    generated_at: datetime
    domains: Mapping[str, Mapping[str, Any]]
    format: str


@dataclass(frozen=True, slots=True)
class DeletionReport:
    user_id: str
    deleted_at: datetime
    per_domain: Mapping[str, int]
    total: int
    failed_domains: tuple[str, ...]


_REGISTRY: dict[str, DomainHandlers] = {}


def register_domain(handlers: DomainHandlers) -> None:
    _REGISTRY[handlers.name] = handlers


def registered_domains() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def get_handlers(name: str) -> DomainHandlers | None:
    return _REGISTRY.get(name)


def all_handlers() -> tuple[DomainHandlers, ...]:
    return tuple(_REGISTRY[name] for name in sorted(_REGISTRY))


def reset_registry() -> None:
    _REGISTRY.clear()


_PROCESS_STORE: dict[tuple[str, str], ProvenanceRef] = {}


def record_provenance(ref: ProvenanceRef, *, now=None) -> None:
    handlers = get_handlers(ref.domain)
    if handlers is not None and handlers.provenance is not None:
        _PROCESS_STORE[(ref.domain, ref.record_id)] = ref
        return
    _PROCESS_STORE[(ref.domain, ref.record_id)] = ref


def resolve_provenance(domain: str, record_id: str) -> ProvenanceRef | None:
    handlers = get_handlers(domain)
    if handlers is not None and handlers.provenance is not None:
        found = handlers.provenance(domain, record_id)
        if found is not None:
            return found
    return _PROCESS_STORE.get((domain, record_id))


def reset_provenance_store() -> None:
    _PROCESS_STORE.clear()


logger = logging.getLogger(__name__)


def delete_user_data(user_id: str, *, now: datetime | None = None) -> DeletionReport:
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
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


def export_user_data(
    user_id: str,
    *,
    fmt: Literal["json", "csv"] = "json",
    now: datetime | None = None,
) -> ExportBundle:
    timestamp = timeutil.ensure_aware(now) or timeutil.now()
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
