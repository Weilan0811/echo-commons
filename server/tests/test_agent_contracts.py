from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError
from support_agent_context import build_test_snapshot

from echo_server.agents.contracts import (
    AgentInvocation,
    AgentRunResult,
    AgentRunStatus,
    AgentStopReason,
    CharacterMessageProposal,
    ContextInputRef,
    ConversationScope,
    Correlation,
    ExecutionPolicy,
    InvocationIdentity,
    InvocationOrigin,
    InvocationPurpose,
    OutputContractRef,
    ProposalEnvelope,
    ProposalKind,
    ProposalOutput,
    RelationshipReflectionAction,
)
from echo_server.domain.relationship import RelationshipEvidenceKind


def _invocation() -> AgentInvocation:
    snapshot = build_test_snapshot()
    return AgentInvocation(
        identity=InvocationIdentity(
            agent_id="xiaojin.character",
            purpose=InvocationPurpose.CONVERSATION_REPLY,
        ),
        scope=ConversationScope(
            conversation_id=snapshot.conversation_id,
            character_id=snapshot.character_id,
        ),
        context=snapshot,
        context_input=ContextInputRef(
            snapshot_id=snapshot.context_version,
            snapshot_schema_version=snapshot.snapshot_version,
            snapshot_fingerprint=snapshot.input_fingerprint,
        ),
        output_contract=OutputContractRef(kind="character_message", version="v2"),
        execution_policy=ExecutionPolicy(max_model_requests=1),
        correlation=Correlation(trace_id=uuid4()),
    )


def _proposal(invocation: AgentInvocation) -> ProposalEnvelope:
    return ProposalEnvelope(
        proposal_id=uuid4(),
        kind=ProposalKind.CHARACTER_MESSAGE,
        origin=InvocationOrigin(invocation_id=invocation.identity.invocation_id),
        payload=CharacterMessageProposal(
            character_id=invocation.scope.character_id,
            thought="我先听听。",
            utterance="我在听。",
        ),
    )


def test_agent_invocation_has_only_grouped_runtime_contracts() -> None:
    invocation = _invocation()

    assert invocation.identity.agent_id == "xiaojin.character"
    assert invocation.scope.kind == "conversation"
    assert invocation.output_contract.schema_id == "character_message.v2"
    assert set(invocation.model_dump()) == {
        "identity",
        "scope",
        "context",
        "context_input",
        "output_contract",
        "execution_policy",
        "correlation",
    }

    with pytest.raises(ValidationError):
        AgentInvocation.model_validate(
            {**invocation.model_dump(mode="python"), "task_id": str(uuid4())}
        )


def test_proposal_envelope_contains_only_review_identity_and_payload() -> None:
    envelope = _proposal(_invocation())

    assert set(envelope.model_dump()) == {"proposal_id", "kind", "origin", "payload"}
    assert envelope.origin.kind == "invocation"

    with pytest.raises(ValidationError):
        ProposalEnvelope.model_validate(
            {**envelope.model_dump(mode="python"), "agent_id": "legacy-agent"}
        )


def test_relationship_reflection_contract_uses_the_model_facing_shape() -> None:
    action = RelationshipReflectionAction.model_validate(
        {
            "kind": "relationship_reflection",
            "evidence_refs": ["message:1"],
            "dimensions": [{"dimension": "affection", "direction": "positive", "level": 1}],
        }
    )

    assert action.dimensions[0].dimension == "affection"
    assert action.dimensions[0].direction == "positive"
    assert action.dimensions[0].level == 1

    with pytest.raises(ValidationError):
        RelationshipReflectionAction.model_validate(
            {
                "kind": "relationship_reflection",
                "evidence_refs": ["message:1"],
                "dimensions": [
                    {
                        "name": "affection",
                        "sentiment": "positive",
                        "level": 1,
                        "reason": "说明",
                    }
                ],
            }
        )


def test_agent_run_result_has_one_typed_output_branch() -> None:
    invocation = _invocation()
    proposal = _proposal(invocation)
    result = AgentRunResult(
        invocation_id=invocation.identity.invocation_id,
        agent_id=invocation.identity.agent_id,
        agent_kind=invocation.identity.agent_kind,
        harness_version=invocation.execution_policy.harness_version,
        model_profile=invocation.execution_policy.model_profile,
        status=AgentRunStatus.COMPLETED,
        stop_reason=AgentStopReason.PROPOSAL_READY,
        output=ProposalOutput(
            proposal=proposal,
            contract=invocation.output_contract,
        ),
    )

    assert result.output is not None
    assert result.output.proposal is proposal
    with pytest.raises(ValidationError):
        AgentRunResult.model_validate(
            {
                **result.model_dump(mode="python"),
                "proposals": [proposal.model_dump(mode="python")],
            }
        )


def test_relationship_evidence_kind_is_a_finite_runtime_vocabulary() -> None:
    assert tuple(item.value for item in RelationshipEvidenceKind) == (
        "interaction",
        "support",
        "conflict",
        "commitment",
    )

    with pytest.raises(ValueError):
        RelationshipEvidenceKind("qualifying_support")
