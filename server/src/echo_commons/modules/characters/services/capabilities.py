from __future__ import annotations

from echo_commons.modules.characters.templates.catalog import CharacterBlueprint


class CapabilityResolver:
    def __init__(self, implemented_tools: frozenset[str]) -> None:
        self.implemented_tools = implemented_tools

    def tools(self, blueprint: CharacterBlueprint, allowed: frozenset[str]) -> tuple[str, ...]:
        return tuple(
            capability.name
            for capability in blueprint.capabilities
            if capability.name in self.implemented_tools
            and capability.name in allowed
            and capability.action_kind == "read"
        )
