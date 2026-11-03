import json
from dataclasses import dataclass

from echo_commons.agents.contracts.invocation import AgentInvocation, InvocationPurpose
from echo_commons.agents.contracts.run import AgentRunResult, AgentRunStatus
from echo_commons.execution.contracts import TaskLease
from echo_commons.modules.memory.domain.organization import FactCorrect, FactSupport
from echo_commons.modules.reflection.budget import ReflectionBudget
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contracts.candidates import (
    MemoryCognitionCandidate,
    MemoryCognitionReflectAction,
    MemoryFactCandidate,
    MemoryFactExtractAction,
    MemoryFactReviewAction,
    NoOpReflectionAction,
    ReflectionBatchProposal,
    ReflectionNodeActionBase,
    RelationshipReflectionAction,
    SegmentSummaryAction,
    ViewRefreshAction,
    business_chars,
)
from echo_commons.modules.reflection.contracts.context import ReflectionNodeInput
from echo_commons.modules.reflection.domain.graph import (
    ReflectionNodeKind,
    content_fingerprint,
    reflection_graph_definition,
)
from echo_commons.modules.reflection.domain.node import ReflectionNodeTask
from echo_commons.modules.reflection.tasks.projection import NodeReferences, select_node_materials
from echo_commons.shared.actors import ActorRef


def relationship_description_required(materials) -> bool:
    for material in materials:
        if material.kind == "formal_fact" and material.fact_kind == "relationship":
            content = json.loads(material.content)
            if (
                content.get("initial_description")
                and content["relationship_type"] != "stranger"
                and content.get("evidence")
            ):
                return True
    return False


@dataclass(frozen=True, slots=True)
class ReflectionReview:
    max_output_chars: int
    budget: ReflectionBudget | None = None

    def check(
        self,
        lease: TaskLease,
        node: ReflectionNodeTask,
        invocation: AgentInvocation,
        result: AgentRunResult,
        action=None,
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
        definition = reflection_graph_definition(context.graph_snapshot.graph_kind).node(
            context.node_key
        )
        action = action if action is not None else result.output.payload
        if not isinstance(action, ReflectionNodeActionBase) or action.kind not in (
            definition.action_kind,
            "no_op",
        ):
            return "reflection_action_mismatch"
        count_limit, char_limit = (
            self.budget or ReflectionBudget(max_output_chars=self.max_output_chars)
        ).for_node(context)
        if isinstance(action, (MemoryFactExtractAction, MemoryFactReviewAction)):
            proposed = tuple(
                MemoryFactCandidate(source_refs=item.evidence_refs, operation=item)
                for item in action.facts
            )
            chars = ReflectionBatchProposal(candidates=proposed).content_chars
        elif isinstance(action, MemoryCognitionReflectAction):
            proposed = tuple(
                MemoryCognitionCandidate(source_refs=item.evidence_refs, operation=item)
                for item in action.cognitions
            )
            chars = ReflectionBatchProposal(candidates=proposed).content_chars
        else:
            chars = business_chars(action)
        if chars > char_limit:
            return "reflection_output_too_long"
        count = len(getattr(action, "facts", ())) + len(getattr(action, "cognitions", ()))
        if count > count_limit:
            return "reflection_candidate_limit_exceeded"
        if isinstance(action, NoOpReflectionAction) and node.node_kind in {
            ReflectionNodeKind.CONTINUITY_COMPRESS,
        }:
            return "reflection_digest_required"
        materials = select_node_materials(context)
        if (
            isinstance(action, NoOpReflectionAction)
            and node.node_kind is ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW
            and relationship_description_required(materials)
        ):
            return "reflection_relationship_description_required"
        allowed = {material.evidence_ref for material in materials if not material.context_only}
        if set(action.evidence_refs) - allowed:
            return "reflection_evidence_unknown"
        if (
            not isinstance(action, NoOpReflectionAction)
            and not action.evidence_refs
            and not allowed
            and not isinstance(action, MemoryCognitionReflectAction)
        ):
            return "reflection_evidence_missing"
        if isinstance(action, RelationshipReflectionAction):
            targets = source_actors(context.graph_snapshot)
            if any(item.target not in targets for item in action.dimensions):
                return "reflection_relationship_target_unknown"
            plan = next(
                (
                    artifact.payload.follow_up
                    for artifact in context.artifacts
                    if isinstance(artifact.payload, SegmentSummaryAction)
                ),
                None,
            )
            permitted = (
                {item.target: set(item.evidence_refs) for item in plan.relationship_targets}
                if plan
                else {}
            )
            if any(
                not set(item.evidence_refs) <= permitted.get(item.target, set())
                for item in action.dimensions
            ):
                return "reflection_relationship_evidence_mismatch"
        if isinstance(action, SegmentSummaryAction):
            targets = source_actors(context.graph_snapshot)
            if any(
                item.target not in targets or not set(item.evidence_refs) <= allowed
                for item in action.follow_up.relationship_targets
            ):
                return "reflection_relationship_evidence_mismatch"
            own = ActorRef("character", context.scope.character_id)
            for item in action.follow_up.relationship_targets:
                target_refs = {
                    material.evidence_ref
                    for material in materials
                    if (
                        (material.kind == "message" and material.message.sender == item.target)
                        or (material.kind == "game_event" and item.target in material.actors)
                    )
                    and not material.context_only
                }
                relevant = target_refs | {
                    material.evidence_ref
                    for material in materials
                    if not material.context_only
                    and (
                        material.kind == "thought"
                        or (material.kind == "message" and material.message.sender == own)
                    )
                }
                if not target_refs.intersection(item.evidence_refs) or not (
                    set(item.evidence_refs) <= relevant
                ):
                    return "reflection_relationship_evidence_mismatch"
        if isinstance(
            action, (MemoryFactExtractAction, MemoryFactReviewAction, MemoryCognitionReflectAction)
        ):
            error = check_memory_action(context, action)
            if error:
                return error
        if isinstance(action, ViewRefreshAction):
            if (
                action.view_kind == "relationship_attitude"
                and len(action.content)
                > (self.budget or ReflectionBudget()).relationship_attitude_max_chars
            ):
                return "reflection_relationship_attitude_too_long"
            if (
                action.view_kind == "core_memory"
                and len(action.content) > (self.budget or ReflectionBudget()).core_memory_max_chars
            ):
                return "reflection_core_memory_too_long"
            if action.view_kind != definition.view_kind:
                return "reflection_view_kind_mismatch"
            if action.view_kind == "core_memory" and (
                not action.supporting_records
                or not all(
                    any(
                        item.source_id == ref.memory_id
                        and item.version == str(ref.version)
                        and item.fact_kind == f"memory_{ref.record_kind}"
                        for item in materials
                    )
                    for ref in action.supporting_records
                )
            ):
                return "reflection_view_memory_unknown"
            if action.view_kind == "relationship_attitude" and (
                action.target is None
                or not any(
                    item.source_id == f"{context.scope.character_id}/{action.target.kind.value}/"
                    f"{action.target.actor_id}"
                    for item in materials
                )
            ):
                return "reflection_view_target_unknown"
        return None


def bind_fact_review(context, decision):
    extracted = next(
        item.payload
        for item in context.artifacts
        if isinstance(item.payload, MemoryFactExtractAction)
    )
    items = extracted.facts
    if sorted(item.item for item in decision.items) != list(range(1, len(items) + 1)):
        raise ValueError("Fact review must cover each candidate exactly once")
    labels = NodeReferences.from_input(context)
    operations, updated = [], set()
    for result in sorted(decision.items, key=lambda value: value.item):
        candidate = items[result.item - 1]
        if result.action == "add":
            operations.append(candidate)
            continue
        ref = labels.records.get(result.target)
        if ref is None or ref.record_kind != "fact" or ref in updated:
            raise ValueError("Fact review requires one permitted old fact per update")
        updated.add(ref)
        values = dict(
            local_key=candidate.local_key, previous=ref, evidence_refs=candidate.evidence_refs
        )
        operations.append(
            FactSupport(**values)
            if result.action == "support"
            else FactCorrect(fact=candidate.fact, **values)
        )
    return MemoryFactReviewAction(facts=tuple(operations), evidence_refs=extracted.evidence_refs)


def check_memory_action(context, action):
    materials = context.graph_snapshot.materials
    actors = set(source_actors(context.graph_snapshot)) | {
        ActorRef("character", context.scope.character_id)
    }
    if context.graph_snapshot.source_kind == "author_material_batch":
        actors = {ActorRef("character", context.scope.character_id)}
    old = {
        (item.fact_kind.removeprefix("memory_"), item.source_id, int(item.version))
        for item in materials
        if item.kind == "formal_fact" and item.fact_kind in ("memory_fact", "memory_cognition")
    }
    if isinstance(action, (MemoryFactExtractAction, MemoryFactReviewAction)):
        items, eligible = (
            action.facts,
            {
                item.evidence_ref
                for item in materials
                if item.kind in ("message", "game_event", "author_chunk")
            },
        )
        keys = [item.local_key for item in items]
        if len(set(keys)) != len(keys):
            return "reflection_fact_key_duplicate"
        previous = [
            (item.previous.memory_id, item.previous.version)
            for item in items
            if item.operation != "add"
        ]
        if len(set(previous)) != len(previous):
            return "reflection_record_update_duplicate"
        for item in items:
            if item.operation != "add" and (
                item.previous.record_kind != "fact"
                or ("fact", item.previous.memory_id, item.previous.version) not in old
            ):
                return "reflection_record_reference_unknown"
            if item.operation != "support" and any(
                actor not in actors for actor in item.fact.participants
            ):
                return "reflection_relationship_target_unknown"
    else:
        old.update(
            ("fact", fact.reference.memory_id, fact.reference.version)
            for artifact in context.artifacts
            if isinstance(artifact.payload, MemoryFactReviewAction)
            for fact in artifact.payload.saved_facts
        )
        items, eligible = (
            action.cognitions,
            {item.evidence_ref for item in materials if item.kind in ("thought", "author_chunk")},
        )
        candidates = {
            fact.local_key
            for predecessor in context.artifacts
            if isinstance(predecessor.payload, MemoryFactReviewAction)
            for fact in predecessor.payload.facts
        }
        for item in items:
            if item.cognition.target is not None and item.cognition.target not in actors:
                return "reflection_relationship_target_unknown"
            if not item.supporting_facts and not item.evidence_refs:
                return "reflection_evidence_missing"
            if item.operation == "replace" and (
                item.previous.record_kind != "cognition"
                or ("cognition", item.previous.memory_id, item.previous.version) not in old
            ):
                return "reflection_record_reference_unknown"
            for support in item.supporting_facts:
                if (support.kind == "candidate" and support.local_key not in candidates) or (
                    support.kind == "saved"
                    and ("fact", support.memory_id, support.version) not in old
                ):
                    return "reflection_record_reference_unknown"
        previous = [
            (item.previous.memory_id, item.previous.version)
            for item in items
            if item.operation == "replace"
        ]
        if len(previous) != len(set(previous)):
            return "reflection_record_update_duplicate"
    individual = {ref for item in items for ref in item.evidence_refs}
    if individual != set(action.evidence_refs):
        return "reflection_evidence_mismatch"
    if individual - eligible:
        return "reflection_evidence_unknown"
    if any(len(set(item.evidence_refs)) != len(item.evidence_refs) for item in items):
        return "reflection_evidence_mismatch"
    return None


def review_facts(commit, lease):
    from uuid import uuid4

    from echo_commons.agents.contracts.errors import ExecutionError
    from echo_commons.agents.contracts.recovery import FailureCategory
    from echo_commons.agents.contracts.run import UsageSummary
    from echo_commons.execution.clock import utc_now
    from echo_commons.execution.lease import LeaseLostError
    from echo_commons.execution.observations import ExecutionEventPayload, ExecutionObservation
    from echo_commons.modules.reflection.domain.graph import EvidenceRef, ReflectionArtifact
    from echo_commons.modules.reflection.tasks.dependencies import bind_ready_inputs
    from echo_commons.modules.reflection.tasks.input import prepare_node_input

    queue = commit.queue
    with queue.database.transaction() as connection:
        now = utc_now()
        node = queue.nodes.get(connection, lease.task_id)
        run = queue.run_for(connection, node)
        if run.is_terminal or not queue.owned(connection, lease, now):
            raise LeaseLostError("Fact review lease expired")
        snapshot = queue.runs.snapshot(
            connection, run.community_id, run.character_id, str(run.graph_run_id)
        )
        commit.contexts.check_sources(connection, snapshot)
        inputs = queue.artifacts.inputs(connection, str(run.graph_run_id), node.input_artifact_refs)
        context = prepare_node_input(
            snapshot,
            graph_run_id=str(run.graph_run_id),
            node_task_id=lease.task_id,
            node_key=node.node_key,
            node_kind=node.node_kind,
            artifacts=inputs,
        )
        if content_fingerprint(context.model_dump(mode="json")) != node.node_input_fingerprint:
            raise ExecutionError("reflection_input_mismatch", FailureCategory.SOURCE)
        action = inputs[0].payload
        if isinstance(action, NoOpReflectionAction):
            facts = ()
        elif isinstance(action, MemoryFactExtractAction) and not any(
            item.kind == "formal_fact" and item.fact_kind == "memory_fact"
            for item in snapshot.materials
        ):
            error = check_memory_action(context, action)
            if error:
                raise ExecutionError(error, FailureCategory.REVIEW)
            facts = action.facts
        else:
            raise ExecutionError("reflection_fact_action_missing", FailureCategory.REVIEW)
        approved = MemoryFactReviewAction(facts=facts, evidence_refs=action.evidence_refs)
        versions = {item.evidence_ref: item.version for item in snapshot.materials}
        artifact = ReflectionArtifact.create(
            artifact_id=uuid4(),
            graph_run_id=run.graph_run_id,
            node_task_id=node.task_id,
            attempt=lease.attempt,
            node_input_fingerprint=node.node_input_fingerprint,
            output_contract=node.output_contract,
            payload=approved.model_dump(mode="json"),
            evidence_refs=tuple(
                EvidenceRef(*ref.split(":", 1), version=versions[ref])
                for ref in action.evidence_refs
            ),
            created_at_utc=now,
        )
        queue.artifacts.add(connection, artifact, {"reviewed_artifact_id": inputs[0].artifact_id})
        queue.nodes.save(
            connection,
            node.complete(
                worker_id=lease.owner,
                now_utc=now,
                artifact=artifact,
                attempt_count=lease.attempt,
                lease_generation=lease.generation,
            ),
        )
        bind_ready_inputs(
            connection, str(run.graph_run_id), now, queue.runs, queue.nodes, queue.artifacts
        )
        queue.recorder.record(
            connection,
            lease,
            "completed",
            ExecutionEventPayload(
                observation=ExecutionObservation(
                    provider_attempt_count=0, usage_summary=UsageSummary()
                )
            ),
            now,
        )
