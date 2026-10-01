"""Typed Agent output proposals and their minimal provenance."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_server.agents.contracts.reflection import ReflectionBatchProposal

CHARACTER_MESSAGE_OUTPUT_SCHEMA = "character_message.v2"
REFLECTION_NODE_OUTPUT_SCHEMA = "reflection_node.v1"


class ProposalKind(StrEnum):
    CHARACTER_MESSAGE = "character_message"
    REFLECTION_BATCH = "reflection_batch"


class CharacterMessageProposal(BaseModel):
    """A character reply with an optional private thought and public utterance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["character_message"] = "character_message"
    character_id: str
    thought: str = ""
    utterance: str
    reply_to_message_id: UUID | None = None

    @model_validator(mode="after")
    def text_fields_must_contain_text(self) -> CharacterMessageProposal:
        if not self.utterance.strip():
            raise ValueError("utterance must contain text")
        return self


class InvocationOrigin(BaseModel):
    """Identity of the Agent invocation that emitted one Proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["invocation"] = "invocation"
    invocation_id: UUID


class ReflectionGraphOrigin(BaseModel):
    """Identity of the graph that aggregated one Reflection Proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["reflection_graph"] = "reflection_graph"
    graph_run_id: UUID


ProposalOrigin: TypeAlias = Annotated[
    InvocationOrigin | ReflectionGraphOrigin,
    Field(discriminator="kind"),
]

ProposalPayload: TypeAlias = Annotated[
    CharacterMessageProposal | ReflectionBatchProposal,
    Field(discriminator="kind"),
]


class ProposalEnvelope(BaseModel):
    """The smallest reviewable Proposal boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID
    kind: ProposalKind
    origin: ProposalOrigin
    payload: ProposalPayload

    @model_validator(mode="after")
    def payload_kind_matches_envelope(self) -> ProposalEnvelope:
        if self.payload.kind != self.kind.value:
            raise ValueError("proposal payload kind does not match envelope kind")
        return self


__all__ = [
    "CHARACTER_MESSAGE_OUTPUT_SCHEMA",
    "REFLECTION_NODE_OUTPUT_SCHEMA",
    "CharacterMessageProposal",
    "InvocationOrigin",
    "ProposalEnvelope",
    "ProposalKind",
    "ProposalOrigin",
    "ProposalPayload",
    "ReflectionBatchProposal",
    "ReflectionGraphOrigin",
]
