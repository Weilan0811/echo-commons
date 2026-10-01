"""Deterministic character Agents implementing the canonical Run boundary."""

from __future__ import annotations

from uuid import uuid4

from echo_server.agents.contracts import (
    AgentInvocation,
    AgentRunResult,
    AgentRunStatus,
    AgentStopReason,
    CharacterMessageProposal,
    ContinuityDigestAction,
    FollowUpDecision,
    InvocationOrigin,
    InvocationPurpose,
    NoOpReflectionAction,
    ProposalEnvelope,
    ProposalKind,
    ProposalOutput,
    ReflectionNodeOutput,
    RelationshipDimensionAction,
    RelationshipReflectionAction,
    SegmentSummaryAction,
    StateReflectionAction,
)


class StubCharacterAgent:
    """Deterministic offline Agent used by local development and API tests."""

    agent_id = "stub-character-agent"
    agent_kind = "character"
    model_profile = "stub"
    harness_version = "stub-v1"

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self._responses = responses or {}

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        character_id = invocation.scope.character_id
        if invocation.identity.purpose is InvocationPurpose.REFLECTION:
            # Offline fallback fixture: the durable Worker still exercises the
            # same Runtime review and commit path as a real Character Agent.
            source_ref = (
                invocation.context.source_refs[0]
                if hasattr(invocation.context, "source_refs") and invocation.context.source_refs
                else "stub:source"
            )
            window = getattr(invocation.context, "window", None)
            action = self._reflection_node_action(
                getattr(invocation.scope, "node_key", None),
                window,
                source_ref,
            )
            return AgentRunResult(
                invocation_id=invocation.identity.invocation_id,
                agent_id=invocation.identity.agent_id,
                agent_kind=invocation.identity.agent_kind,
                harness_version=self.harness_version,
                model_profile=self.model_profile,
                status=AgentRunStatus.COMPLETED,
                stop_reason=AgentStopReason.PROPOSAL_READY,
                output=ReflectionNodeOutput(
                    contract=invocation.output_contract,
                    action=action,
                ),
            )
        payload = CharacterMessageProposal(
            character_id=character_id,
            thought="我先接住对方的话。",
            utterance=self._responses.get(character_id, "我在听。"),
            reply_to_message_id=invocation.context.trigger_message.message_id,
        )
        proposal_kind = ProposalKind.CHARACTER_MESSAGE
        proposal = ProposalEnvelope(
            proposal_id=uuid4(),
            kind=proposal_kind,
            origin=InvocationOrigin(
                invocation_id=invocation.identity.invocation_id,
            ),
            payload=payload,
        )
        return AgentRunResult(
            invocation_id=invocation.identity.invocation_id,
            agent_id=invocation.identity.agent_id,
            agent_kind=invocation.identity.agent_kind,
            harness_version=self.harness_version,
            model_profile=self.model_profile,
            status=AgentRunStatus.COMPLETED,
            stop_reason=AgentStopReason.PROPOSAL_READY,
            output=ProposalOutput(
                proposal=proposal,
                contract=invocation.output_contract,
            ),
        )

    @staticmethod
    def _reflection_node_action(node_kind, window, source_ref):
        evidence = (source_ref,)
        if node_kind == "relationship_reflect":
            return RelationshipReflectionAction(
                dimensions=(
                    RelationshipDimensionAction(
                        dimension="affection",
                        direction="positive",
                        level=1,
                    ),
                ),
                evidence_refs=evidence,
            )
        if node_kind == "state_reflect":
            return StateReflectionAction(
                state_kind="mood",
                value="平静",
                evidence_refs=evidence,
            )
        if node_kind == "continuity_compress":
            return ContinuityDigestAction(
                content="最近的交流保持着连续的陪伴感。",
                covers_through_sequence=(
                    window.last_message_sequence
                    if window is not None and window.last_message_sequence is not None
                    else 0
                ),
                evidence_refs=evidence,
            )
        if (
            node_kind == "segment_summary_plan"
            and window is not None
            and window.first_message_sequence is not None
            and window.last_message_sequence is not None
        ):
            return SegmentSummaryAction(
                summary="对方刚刚和我有过一次交流。",
                follow_up=FollowUpDecision(
                    relationship_reflect=True,
                    state_reflect=True,
                ),
                evidence_refs=evidence,
            )
        return NoOpReflectionAction(reason="stub reflection node has no configured action")


class FailingCharacterAgent:
    """Agent fixture that always raises a controlled run-time failure."""

    agent_id = "failing-character-agent"
    agent_kind = "character"
    model_profile = "stub"
    harness_version = "stub-v1"

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error or RuntimeError("stub_agent_failure")

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        raise self.error
