from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping

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
