"""Model output parsing into the Echo-native Agent Contract."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from echo_server.agents.contracts import (
    REFLECTION_NODE_OUTPUT_SCHEMA,
    AgentInvocation,
    AgentOutput,
    CharacterMessageProposal,
    InvocationOrigin,
    InvocationPurpose,
    ProposalEnvelope,
    ProposalKind,
    ProposalOutput,
    ReflectionNodeAction,
    ReflectionNodeOutput,
)
from echo_server.services.model_gateway.protocol import ModelResponse, ModelResponseKind


class ModelOutputError(ValueError):
    code = "invalid_model_output"


class ProposalKindNotAllowedError(ModelOutputError):
    code = "proposal_kind_not_allowed"


class CharacterMessageModelOutput(BaseModel):
    """The terminal content returned by a Character Agent model."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    thought: str = ""
    utterance: str = Field(min_length=1)

    @field_validator("utterance")
    @classmethod
    def utterance_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("utterance must contain text")
        return value


_character_message_output_adapter = TypeAdapter(CharacterMessageModelOutput)


_reflection_node_action_adapter = TypeAdapter(ReflectionNodeAction)


def parse_terminal_output(
    response: ModelResponse,
    invocation: AgentInvocation,
) -> AgentOutput:
    """Parse one terminal provider response into exactly one output branch."""

    if response.kind is not ModelResponseKind.TERMINAL or response.output is None:
        raise ModelOutputError("model response is not a terminal Agent output")

    if invocation.output_contract.kind == "reflection_node":
        if invocation.identity.purpose is not InvocationPurpose.REFLECTION:
            raise ProposalKindNotAllowedError("reflection node output requires reflection purpose")
        if invocation.output_contract.schema_id != REFLECTION_NODE_OUTPUT_SCHEMA:
            raise ProposalKindNotAllowedError("unsupported reflection node output contract")
        return _parse_reflection_node(response, invocation)

    if invocation.output_contract.schema_id != "character_message.v2":
        raise ProposalKindNotAllowedError("character message Proposal is not allowed")
    return ProposalOutput(
        proposal=_parse_character_message(response, invocation),
        contract=invocation.output_contract,
    )


def _parse_character_message(
    response: ModelResponse,
    invocation: AgentInvocation,
) -> ProposalEnvelope:
    if not hasattr(invocation.context, "trigger_message"):
        raise ModelOutputError("character message requires a conversation context")
    try:
        model_output = _character_message_output_adapter.validate_python(response.output)
    except ValidationError as exc:
        raise ModelOutputError("character reply content is invalid") from exc
    payload = CharacterMessageProposal(
        kind=ProposalKind.CHARACTER_MESSAGE.value,
        character_id=invocation.scope.character_id,
        thought=model_output.thought,
        utterance=model_output.utterance,
        reply_to_message_id=invocation.context.trigger_message.message_id,
    )
    return ProposalEnvelope(
        proposal_id=uuid4(),
        kind=ProposalKind.CHARACTER_MESSAGE,
        payload=payload,
        origin=InvocationOrigin(
            invocation_id=invocation.identity.invocation_id,
        ),
    )


def _parse_reflection_node(
    response: ModelResponse,
    invocation: AgentInvocation,
) -> ReflectionNodeOutput:
    contract = invocation.output_contract
    try:
        action = _reflection_node_action_adapter.validate_python(response.output)
    except ValidationError as exc:
        raise ModelOutputError("reflection node action content is invalid") from exc
    return ReflectionNodeOutput(contract=contract, action=action)


__all__ = [
    "CharacterMessageModelOutput",
    "ModelOutputError",
    "ProposalKindNotAllowedError",
    "parse_terminal_output",
]
