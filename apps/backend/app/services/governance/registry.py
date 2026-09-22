from __future__ import annotations

from app.services.governance.models import DomainHandlers

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
