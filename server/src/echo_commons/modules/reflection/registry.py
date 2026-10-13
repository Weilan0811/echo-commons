from types import MappingProxyType

from echo_commons.modules.reflection.domain.graph import (
    ReflectionGraphDefinition,
    ReflectionGraphKind,
    reflection_graph_definition,
)


class ReflectionGraphRegistry:
    def __init__(self) -> None:
        self._definitions = MappingProxyType(
            {
                kind: reflection_graph_definition(kind)
                for kind in ReflectionGraphKind
                if kind is not ReflectionGraphKind.DIARY_COMPOSE
            }
        )

    def require(
        self, graph_kind: ReflectionGraphKind, version: str | None = None
    ) -> ReflectionGraphDefinition:
        definition = self._definitions[graph_kind]
        if version is not None and definition.version != version:
            raise LookupError(f"Reflection graph version does not exist: {graph_kind}:{version}")
        return definition

    @property
    def definitions(self) -> tuple[ReflectionGraphDefinition, ...]:
        return tuple(self._definitions.values())
