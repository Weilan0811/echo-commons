from dataclasses import dataclass

from echo_commons.agents.contracts.invocation import AgentInvocation, InvocationPurpose
from echo_commons.agents.contracts.run import AgentRunResult, AgentRunStatus
from echo_commons.execution.contracts import TaskLease
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contracts.candidates import (
    ContinuityDigestAction,
    GraphExtractionAction,
    NoOpReflectionAction,
    ReflectionNodeActionBase,
    RelationshipReflectionAction,
)
from echo_commons.modules.reflection.contracts.context import ReflectionNodeInput
from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind, content_fingerprint
from echo_commons.modules.reflection.domain.node import ReflectionNodeTask
from echo_commons.modules.reflection.tasks.projection import project_node_input

_KINDS = {
    ReflectionNodeKind.SEGMENT_SUMMARY_PLAN: "segment_summary",
    ReflectionNodeKind.RELATIONSHIP_REFLECT: "relationship_reflection",
    ReflectionNodeKind.STATE_REFLECT: "state_reflection",
    ReflectionNodeKind.CONTINUITY_COMPRESS: "continuity_digest",
    ReflectionNodeKind.PAGE_COMPOSE: "long_term_memory_page",
    ReflectionNodeKind.GRAPH_EXTRACT: "graph_extraction",
}


@dataclass(frozen=True, slots=True)
class ReflectionReview:
    max_output_chars: int

    def check(
        self,
        lease: TaskLease,
        node: ReflectionNodeTask,
        invocation: AgentInvocation,
        result: AgentRunResult,
    ) -> str | None:
        context = invocation.context
        if (
            not isinstance(context, ReflectionNodeInput)
            or invocation.identity.purpose is not InvocationPurpose.REFLECTION
            or invocation.scope.task_id != str(node.task_id)
            or lease.task_id != str(node.task_id)
            or lease.attempt != invocation.identity.attempt
            or lease.trace_id != str(invocation.correlation.trace_id)
            or context.graph_run_id != str(node.graph_run_id)
            or invocation.scope.source_kind != "reflection_graph"
            or invocation.scope.source_id != str(node.graph_run_id)
            or result.invocation_id != invocation.identity.invocation_id
            or result.agent_id != invocation.identity.agent_id
            or result.agent_kind != "character"
            or result.model_profile != invocation.execution_policy.model_profile
            or result.harness_version != invocation.execution_policy.harness_version
        ):
            return "invocation_identity_mismatch"
        if content_fingerprint(context.model_dump(mode="json")) != node.node_input_fingerprint:
            return "reflection_input_mismatch"
        if result.status is not AgentRunStatus.COMPLETED or result.output is None:
            return "reflection_output_missing"
        if (
            result.output.contract != invocation.output_contract
            or result.output.contract.kind != node.output_contract.kind
            or result.output.contract.version != node.output_contract.version
        ):
            return "reflection_contract_mismatch"
        action = result.output.payload
        if not isinstance(action, ReflectionNodeActionBase) or action.kind not in (
            _KINDS[node.node_kind],
            "no_op",
        ):
            return "reflection_action_mismatch"
        if len(action.model_dump_json()) > self.max_output_chars:
            return "reflection_output_too_long"
        if isinstance(action, NoOpReflectionAction) and node.node_kind in {
            ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
            ReflectionNodeKind.CONTINUITY_COMPRESS,
        }:
            return (
                "reflection_digest_required"
                if node.node_kind is ReflectionNodeKind.CONTINUITY_COMPRESS
                else "reflection_summary_required"
            )
        allowed = set(project_node_input(context).evidence_refs)
        if set(action.evidence_refs) - allowed:
            return "reflection_evidence_unknown"
        if (
            not isinstance(action, NoOpReflectionAction)
            and not action.evidence_refs
            and not allowed
        ):
            return "reflection_evidence_missing"
        if isinstance(action, RelationshipReflectionAction):
            targets = source_actors(context.graph_snapshot)
            if any(item.target not in targets for item in action.dimensions):
                return "reflection_relationship_target_unknown"
        if isinstance(action, ContinuityDigestAction):
            upper = max(
                material.last_sequence
                for material in context.graph_snapshot.materials
                if material.kind == "segment_summary"
            )
            if action.covers_through_sequence != upper:
                return "reflection_digest_coverage_mismatch"
        if isinstance(action, GraphExtractionAction):
            identifiers = {item.entity_id for item in action.entities}
            if len(identifiers) != len(action.entities):
                return "reflection_entity_duplicate"
            if any(
                edge.from_entity_id not in identifiers or edge.to_entity_id not in identifiers
                for edge in action.edges
            ):
                return "reflection_edge_target_unknown"
        return None
