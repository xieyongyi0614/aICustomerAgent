from __future__ import annotations

from app.services.governance.models import ProvenanceRef
from app.services.governance.registry import get_handlers

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
