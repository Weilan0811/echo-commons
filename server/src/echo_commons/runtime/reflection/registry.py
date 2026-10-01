from __future__ import annotations

from collections.abc import Iterable

from echo_commons.domain.errors import DomainInvariantError, require_non_empty
from echo_commons.domain.reflection_graph import (
    ReflectionGraphDefinition,
    ReflectionGraphKind,
    reflection_graph_definition,
)


class ReflectionGraphRegistry:
    """Expose only the five graph definitions frozen by the refactor ADR."""

    def __init__(
        self,
        definitions: Iterable[ReflectionGraphDefinition] | None = None,
    ) -> None:
        values = (
            tuple(definitions)
            if definitions is not None
            else tuple(reflection_graph_definition(kind) for kind in ReflectionGraphKind)
        )
        if not values:
            raise DomainInvariantError("reflection graph registry cannot be empty")
        by_identity: dict[tuple[str, str], ReflectionGraphDefinition] = {}
        for definition in values:
            if not isinstance(definition, ReflectionGraphDefinition):
                raise DomainInvariantError(
                    "reflection graph registry contains an invalid definition"
                )
            identity = (
                str(getattr(definition.graph_kind, "value", definition.graph_kind)),
                definition.version,
            )
            if identity in by_identity:
                raise DomainInvariantError(
                    "reflection graph registry contains a duplicate definition"
                )
            by_identity[identity] = definition
        self._definitions = by_identity

    def get(
        self,
        graph_kind: ReflectionGraphKind | str,
        version: str = "v1",
    ) -> ReflectionGraphDefinition | None:
        kind = str(getattr(graph_kind, "value", graph_kind))
        return self._definitions.get((kind, require_non_empty(version, "graph version")))

    def require(
        self,
        graph_kind: ReflectionGraphKind | str,
        version: str = "v1",
    ) -> ReflectionGraphDefinition:
        definition = self.get(graph_kind, version)
        if definition is None:
            kind = str(getattr(graph_kind, "value", graph_kind))
            raise LookupError(f"reflection graph is not registered: {kind}:{version}")
        return definition

    @property
    def definitions(self) -> tuple[ReflectionGraphDefinition, ...]:
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions, key=lambda item: (item[0], item[1]))
        )


__all__ = ["ReflectionGraphRegistry"]
