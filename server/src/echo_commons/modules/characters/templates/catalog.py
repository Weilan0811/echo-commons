from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from echo_commons.modules.characters.domain.state import InitialState
from echo_commons.modules.memory.domain.authored import AuthorMaterial
from echo_commons.shared.errors import ConflictError, NotFoundError


@dataclass(frozen=True, slots=True)
class IdentityResource:
    """One validated Markdown resource and its versioned metadata."""

    schema_version: int
    resource_type: str
    resource_id: str
    content_version: str
    status: str
    locale: str
    updated_at: str
    content: str
    source_ref: str | None = None
    relative_path: str = ""


@dataclass(frozen=True, slots=True)
class IdentityCapability:
    """One static action advertised by a character resource bundle."""

    name: str
    description: str
    parameters_json: str
    action_kind: str = "read"

    @property
    def parameters(self) -> dict[str, object]:
        return json.loads(self.parameters_json)


@dataclass(frozen=True, slots=True)
class CapabilitiesResource:
    """Validated YAML metadata and static capability definitions."""

    schema_version: int
    resource_type: str
    resource_id: str
    content_version: str
    status: str
    locale: str
    updated_at: str
    capabilities: tuple[IdentityCapability, ...]
    source_ref: str | None = None
    relative_path: str = ""


@dataclass(frozen=True, slots=True)
class AuthoredMemory:
    """One stable author-provided memory page from a character bundle."""

    memory_id: str
    memory_kind: str
    content: str
    visibility: str = "resident"
    confidence: float = 1.0
    salience: float = 0.5


@dataclass(frozen=True, slots=True)
class MemoryPreloadResource:
    """Versioned author preload pages that seed a character's own past."""

    schema_version: int
    resource_type: str
    resource_id: str
    content_version: str
    status: str
    locale: str
    updated_at: str
    memories: tuple[AuthoredMemory, ...]
    source_ref: str | None = None
    relative_path: str = ""


@dataclass(frozen=True, slots=True)
class CharacterBlueprint:
    """A character bundle with independently versioned prompt resources."""

    resource_id: str
    display_name: str
    content_version: str
    status: str
    locale: str
    updated_at: str
    profile: IdentityResource
    voice: IdentityResource | None = None
    relational_dynamics: IdentityResource | None = None
    capabilities_resource: CapabilitiesResource | None = None
    memory_preload: MemoryPreloadResource | None = None
    source_ref: str | None = None
    relative_path: str = ""
    avatar_url: str | None = None
    illustration_url: str | None = None
    avatar_asset_id: str | None = None
    initial_state: InitialState = field(default_factory=InitialState)

    @property
    def capabilities(self) -> tuple[IdentityCapability, ...]:
        if self.capabilities_resource is None:
            return ()
        return self.capabilities_resource.capabilities


@dataclass(frozen=True, slots=True)
class BlueprintCatalog:
    schema_version: int
    bundle_version: str
    agent_contract: IdentityResource
    blueprints: Mapping[str, CharacterBlueprint]

    def __post_init__(self) -> None:
        object.__setattr__(self, "blueprints", MappingProxyType(dict(self.blueprints)))

    def blueprint(self, blueprint_id: str) -> CharacterBlueprint:
        return self.blueprints[blueprint_id]

    def author_materials(
        self, connection: sqlite3.Connection, blueprint_id: str, version: str
    ) -> tuple[AuthorMaterial, ...]:
        self.get(connection, blueprint_id, version)
        return ()

    def get(
        self,
        connection: sqlite3.Connection,
        blueprint_id: str,
        version: str | None = None,
    ) -> CharacterBlueprint:
        if blueprint_id not in self.blueprints:
            raise NotFoundError("Character blueprint does not exist")
        blueprint = self.blueprint(blueprint_id)
        if version is not None and blueprint.content_version != version:
            raise ConflictError("Bound blueprint version is unavailable")
        return blueprint

    def require_instantiable(
        self,
        connection: sqlite3.Connection,
        blueprint_id: str,
        player_id: str | None,
    ) -> CharacterBlueprint:
        return self.get(connection, blueprint_id)
