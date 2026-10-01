from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


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

    @property
    def version(self) -> str:
        """Short alias used by context and trace projections."""

        return self.content_version

    @property
    def body(self) -> str:
        """Return the Markdown body without YAML frontmatter."""

        return self.content


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

    @property
    def version(self) -> str:
        return self.content_version


@dataclass(frozen=True, slots=True)
class AuthoredMemory:
    """One stable author-provided memory page from a character bundle."""

    memory_id: str
    memory_kind: str
    content: str
    visibility: str = "resident"
    confidence: float = 1.0
    salience: float = 0.5
    subject_kind: str = "self"
    subject_id: str = "self"


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

    @property
    def version(self) -> str:
        return self.content_version


@dataclass(frozen=True, slots=True)
class CharacterBlueprint:
    """A character bundle with independently versioned prompt resources."""

    resource_id: str
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

    @property
    def version(self) -> str:
        return self.content_version

    @property
    def content(self) -> str:
        """组合实际人物正文。"""

        parts = [self.profile.content]
        if self.relational_dynamics is not None:
            parts.append(self.relational_dynamics.content)
        if self.voice is not None:
            parts.append(self.voice.content)
        return "\n\n".join(parts)

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
