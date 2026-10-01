"""Provider-neutral context supplied to a Reflection Agent Run.

Reflection uses the same character identity and character state/relationship
projections as a conversation run, but it does not pretend that a source window is a chat
request.  The window metadata and bounded source materials therefore live in
their own immutable contract.  The Reflection Worker will build this object
before invoking the Agent and may replace the material projection without
changing the task identity or output protocol.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from echo_server.agents.contracts.context import (
    CharacterStateSnapshot,
    IdentityContext,
    MemoryContext,
    RelationshipStateSnapshot,
)


def _named_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must contain text")
    return normalized


class ReflectionSourceMaterial(BaseModel):
    """One bounded, provenance-labelled item from the selected source window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_ref: str = Field(min_length=1, max_length=300)
    source_kind: str = Field(min_length=1, max_length=100)
    content_version: str = ""
    content: str = Field(min_length=1, max_length=12000)
    occurred_at_utc: datetime | None = None

    @field_validator("source_ref", "source_kind", "content")
    @classmethod
    def fields_must_contain_text(cls, value: str, info: object) -> str:
        return _named_text(value, getattr(info, "field_name", "value"))


class ReflectionWindowContext(BaseModel):
    """The Runtime-owned message range for the reflection materials."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    first_message_sequence: int | None = None
    last_message_sequence: int | None = None

    @model_validator(mode="after")
    def message_range_must_be_ordered(self) -> ReflectionWindowContext:
        if (
            self.first_message_sequence is not None
            and self.last_message_sequence is not None
            and self.first_message_sequence > self.last_message_sequence
        ):
            raise ValueError("reflection message range must be ordered")
        return self


class ReflectionContext(BaseModel):
    """Immutable reflection input assembled from one Runtime read boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    character_id: str = Field(min_length=1, max_length=200)
    now_utc: datetime
    identity: IdentityContext
    character_state: CharacterStateSnapshot
    relationship_state: RelationshipStateSnapshot
    memory_context: MemoryContext = Field(default_factory=MemoryContext)
    window: ReflectionWindowContext
    materials: tuple[ReflectionSourceMaterial, ...] = Field(default=(), max_length=256)

    @field_validator("character_id")
    @classmethod
    def identity_fields_must_contain_text(cls, value: str, info: object) -> str:
        return _named_text(value, getattr(info, "field_name", "value"))

    @model_validator(mode="after")
    def character_identity_must_match(self) -> ReflectionContext:
        if self.identity.character_id != self.character_id:
            raise ValueError("identity character_id does not match reflection character_id")
        if self.character_state.character_id != self.character_id:
            raise ValueError("character state character_id does not match reflection character_id")
        source_refs = [material.source_ref for material in self.materials]
        if len(source_refs) != len(set(source_refs)):
            raise ValueError("reflection materials must not repeat source_ref")
        return self

    @property
    def source_refs(self) -> tuple[str, ...]:
        """Stable source references available to the Reflection Reviewer."""

        return tuple(material.source_ref for material in self.materials)


__all__ = [
    "ReflectionContext",
    "ReflectionSourceMaterial",
    "ReflectionWindowContext",
]
