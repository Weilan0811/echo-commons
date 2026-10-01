"""The Runtime-facing boundary for a configured Character Agent.

The wrapper deliberately stays thin.  It binds a generic Harness backend to
one character identity and validates the immutable invocation before handing
it to the backend.  It does not load repositories, own character state, or
turn model output into authoritative game facts.
"""

from __future__ import annotations

from echo_server.agents.contracts import (
    AgentCapabilities,
    AgentDescriptor,
    AgentInvocation,
    AgentPurposeCapabilities,
    AgentRunResult,
    InvocationPurpose,
    OutputContractRef,
    RunnableAgent,
)
from echo_server.services.model_gateway import ModelRoute, resolve_agent_route


class CharacterAgentInvocationError(ValueError):
    """Raised when an invocation does not belong to this Character Agent."""

    code = "character_agent_invocation_invalid"


class CharacterAgent:
    """Bind one configured Harness backend to one character identity."""

    agent_kind = "character"

    def __init__(
        self,
        backend: RunnableAgent,
        *,
        character_id: str,
        agent_id: str | None = None,
        available_tools: tuple[str, ...] = (),
    ) -> None:
        normalized_character_id = character_id.strip()
        if not normalized_character_id:
            raise ValueError("character id must be named")
        resolved_agent_id = (agent_id or f"{normalized_character_id}.character").strip()
        if not resolved_agent_id:
            raise ValueError("character agent id must be named")
        self.backend = backend
        self.character_id = normalized_character_id
        self.agent_id = resolved_agent_id
        self.available_tools = tuple(sorted(set(available_tools)))

    @property
    def model_profile(self) -> str:
        """Expose the backend's default profile for legacy Runtime observers."""

        profile = getattr(self.backend, "model_profile", "light")
        return profile if isinstance(profile, str) and profile.strip() else "light"

    @property
    def harness_version(self) -> str:
        """Expose the selected backend version for Runtime results and traces."""

        version = getattr(self.backend, "harness_version", "unknown")
        return version if isinstance(version, str) and version.strip() else "unknown"

    @property
    def capabilities(self) -> AgentCapabilities:
        """Expose the small purpose matrix used by Runtime registration.

        The matrix is local until the durable AgentCatalog is implemented;
        Reflection already uses it to gate the persistent task target.
        """

        # TEMPORARY COMPATIBILITY: move this matrix to AgentCatalog when the
        # durable multi-agent catalog is implemented.
        return AgentCapabilities(
            purpose_capabilities=(
                AgentPurposeCapabilities(
                    purpose=InvocationPurpose.CONVERSATION_REPLY,
                    allowed_output_contracts=(
                        OutputContractRef(kind="character_message", version="v2"),
                    ),
                    allowed_tools=self.available_tools,
                ),
                AgentPurposeCapabilities(
                    purpose=InvocationPurpose.REFLECTION,
                    allowed_output_contracts=(
                        OutputContractRef(kind="reflection_node", version="v1"),
                    ),
                ),
            )
        )

    @property
    def descriptor(self) -> AgentDescriptor:
        """Return a Runtime-readable descriptor for this bound Character Agent."""

        return AgentDescriptor(
            agent_id=self.agent_id,
            agent_kind=self.agent_kind,
            harness_version=self.harness_version,
            model_profile=self.model_profile,
            capabilities=self.capabilities,
        )

    def route_for(self, task_kind: str) -> ModelRoute:
        """Resolve task routing through the selected backend when available."""

        return resolve_agent_route(self.backend, task_kind)

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        self._validate_invocation(invocation)
        return await self.backend.run(invocation)

    def _validate_invocation(self, invocation: AgentInvocation) -> None:
        if invocation.identity.agent_id != self.agent_id:
            raise CharacterAgentInvocationError(
                "invocation agent id does not match character agent"
            )
        if invocation.identity.agent_kind != self.agent_kind:
            raise CharacterAgentInvocationError("invocation agent kind is not character")
        if invocation.scope.character_id != self.character_id:
            raise CharacterAgentInvocationError(
                "invocation context character does not match character agent"
            )
        purpose_capability = self.capabilities.for_purpose(invocation.identity.purpose)
        if purpose_capability is None:
            raise CharacterAgentInvocationError(
                "invocation purpose is not registered for character agent"
            )
        if not purpose_capability.allows_output_contract(invocation.output_contract):
            raise CharacterAgentInvocationError(
                "invocation output contract exceeds character agent capability"
            )
        if not set(invocation.execution_policy.allowed_tools).issubset(
            purpose_capability.allowed_tools
        ):
            raise CharacterAgentInvocationError(
                "invocation tools exceed character agent capability"
            )


__all__ = ["CharacterAgent", "CharacterAgentInvocationError"]
