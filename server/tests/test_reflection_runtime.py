from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from support_faults import MutableClock

from echo_server.agents.contracts import (
    AgentInvocation,
    AgentRunResult,
    AgentRunStatus,
    AgentStopReason,
    FollowUpDecision,
    GraphEdgeAction,
    GraphEntityAction,
    GraphExtractionAction,
    LongTermMemoryPageAction,
    LongTermMemoryPageItem,
    ReflectionNodeOutput,
)
from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.domain.conversation import ConversationParticipant
from echo_server.domain.memory import MemorySegmentStatus
from echo_server.domain.memory_sources import content_version
from echo_server.domain.messages import SubmitMessageCommand
from echo_server.domain.relationship import RelationshipKey, RelationshipTargetKind
from echo_server.domain.state import CharacterAvailabilityStatus, CharacterState, WorldState
from echo_server.runtime.application_runtime import ApplicationRuntime
from echo_server.runtime.conversation_worker import ConversationWorker
from echo_server.runtime.reflection import (
    ContinuityCompressionTrigger,
    MemoryOrganizationTrigger,
)
from echo_server.store.database import Database
from echo_server.store.memory_provenance import MemoryProvenanceRepository

BASE_TIME = datetime(2026, 9, 19, 12, tzinfo=UTC)


@pytest_asyncio.fixture
async def runtime(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
        lease_seconds=30,
        lease_heartbeat_interval_seconds=5,
    )
    clock = MutableClock(BASE_TIME)
    value = ApplicationRuntime(
        Database(settings.database_path),
        StubCharacterAgent(),
        settings,
        clock=clock,
        worker_id="reflection-runtime",
    )
    await value.start()
    async with value.database.transaction(immediate=True) as connection:
        await value.world_states.save(
            WorldState(state_version=0, world_time_utc=BASE_TIME, updated_at_utc=BASE_TIME),
            connection=connection,
        )
        await value.character_states.save(
            CharacterState(
                character_id="xiaojin",
                availability_status=CharacterAvailabilityStatus.AVAILABLE,
                state_version=0,
                updated_at_utc=BASE_TIME,
            ),
            connection=connection,
        )
        await value.participants.save(
            ConversationParticipant(
                conversation_id="xiaojin",
                character_id="xiaojin",
                joined_at_utc=BASE_TIME,
            ),
            account_id="local-player",
            connection=connection,
        )
    await value.submit_message(
        SubmitMessageCommand(
            account_id="local-player",
            conversation_id="xiaojin",
            player_text="你好",
            images=(),
            client_msg_id=uuid4(),
            local_timestamp=BASE_TIME,
        )
    )
    clock.current = BASE_TIME + timedelta(seconds=6)
    assert await ConversationWorker(value).run_once()
    try:
        yield value
    finally:
        if value.database.is_open:
            await value.stop()


async def _segment(runtime: ApplicationRuntime):
    segment = await runtime.seal_unsegmented_messages(
        "local-player", "xiaojin", "xiaojin", now_utc=runtime.clock()
    )
    assert segment is not None
    assert (segment.first_message_sequence, segment.last_message_sequence) == (1, 2)
    assert segment.status is MemorySegmentStatus.SEALED
    return segment


async def _dispatch_graph(runtime: ApplicationRuntime, *, limit: int = 20) -> int:
    count = 0
    for _ in range(limit):
        if not await runtime.reflection_graph_dispatcher.dispatch_once():
            break
        count += 1
    return count


@pytest.mark.asyncio
async def test_segment_schedule_runs_one_graph_and_is_idempotent(runtime):
    segment = await _segment(runtime)
    async with runtime.database.transaction() as connection:
        sources = await MemoryProvenanceRepository().segment_sources(
            str(segment.segment_id), connection=connection
        )
    assert [source.kind.value for source in sources] == ["message", "message", "thought"]
    assert segment.source_version == content_version(
        [(source.kind.value, source.source_id, source.version) for source in sources]
    )
    assert segment.source_version != content_version(
        [(source.kind.value, source.source_id, source.version) for source in sources[:2]]
    )
    first = await runtime.schedule_segment_reflection(segment.segment_id)
    repeated = await runtime.schedule_segment_reflection(segment.segment_id)

    assert repeated.graph_run.graph_run_id == first.graph_run.graph_run_id
    assert any(
        source.kind == "memory_segment"
        and source.ref == str(segment.segment_id)
        and source.version == segment.source_version
        for source in first.graph_run.source_scope.sources
    )
    runtime.clock.current += timedelta(minutes=1)
    count = await _dispatch_graph(runtime)
    assert count == 4

    stored = await runtime.reflection_graph_runs.get(first.graph_run.graph_run_id)
    assert stored is not None and stored.status.value == "completed"
    tasks = await runtime.reflection_graph_nodes.list_for_graph(stored.graph_run_id)
    assert {task.node_key for task in tasks} == {
        "segment_summary_plan",
        "relationship_reflect",
        "state_reflect",
        "segment_aggregate",
    }
    assert all(task.status.value == "completed" for task in tasks)
    artifacts = await runtime.reflection_graph_artifacts.list_for_graph(stored.graph_run_id)
    assert len(artifacts) == 4
    review = await runtime.reflection_graph_results.get_for_graph(stored.graph_run_id)
    assert review is not None and review.status.value == "approved"
    await runtime.flush_trace_outbox()
    view = await runtime.reflection_run_view.get(stored.graph_run_id)
    assert view is not None
    assert view.graph_run.graph_run_id == stored.graph_run_id
    assert len(view.node_tasks) == 4
    assert len(view.artifacts) == 4
    assert view.result is not None
    trace_kinds = {trace.kind for trace in view.traces}
    assert {
        "reflection_graph.started",
        "reflection_graph.reviewed",
        "reflection_facts.committed",
        "reflection_graph.completed",
    } <= trace_kinds
    assert any(fact.fact_kind == "segment" for fact in view.facts)
    assert view.to_payload()["graphRun"]
    current_segment = await runtime.memory_segments.get(segment.segment_id)
    assert current_segment is not None
    assert current_segment.status is MemorySegmentStatus.INGESTED
    assert current_segment.summary_text == "对方刚刚和我有过一次交流。"
    state_entries = await runtime.character_state_entries.list_latest_for_character("xiaojin")
    assert any(
        entry.state_kind.value == "mood" and entry.value == "平静" for entry in state_entries
    )
    relationship = await runtime.relationship_states.get(
        RelationshipKey(
            account_id="local-player",
            observer_character_id="xiaojin",
            target_kind=RelationshipTargetKind.ACCOUNT,
            target_id="local-player",
        )
    )
    assert relationship is not None and relationship.values.affection > 50.0
    coverage = await runtime.database.fetchall(
        "SELECT source_kind, source_id, source_version FROM memory_source_coverage "
        "WHERE owner_kind = 'segment_summary' AND owner_id = ?",
        (str(segment.segment_id),),
    )
    assert {tuple(row) for row in coverage} == {
        (source.kind.value, source.source_id, source.version) for source in sources
    }

    fact_counts = [
        (await runtime.database.fetchone(f"SELECT COUNT(*) AS count FROM {table}"))["count"]
        for table in ("relation_evidence", "character_state_entries", "memory_source_coverage")
    ]
    completed_repeat = await runtime.schedule_segment_reflection(segment.segment_id)
    assert completed_repeat.graph_run.graph_run_id == stored.graph_run_id
    assert completed_repeat.graph_run.status.value == "completed"
    assert not await runtime.reflection_graph_dispatcher.dispatch_once()
    assert fact_counts == [
        (await runtime.database.fetchone(f"SELECT COUNT(*) AS count FROM {table}"))["count"]
        for table in ("relation_evidence", "character_state_entries", "memory_source_coverage")
    ]
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM reflection_graph_runs WHERE graph_run_id = ?",
            (str(stored.graph_run_id),),
        )
    )["count"] == 1

    await runtime.stop()
    restarted = ApplicationRuntime(
        Database(runtime.settings.database_path),
        StubCharacterAgent(),
        runtime.settings,
        clock=runtime.clock,
        worker_id="reflection-runtime-restarted",
    )
    await restarted.start()
    try:
        after_restart = await restarted.schedule_segment_reflection(segment.segment_id)
        assert after_restart.graph_run.graph_run_id == stored.graph_run_id
        assert after_restart.graph_run.status.value == "completed"
        assert not await restarted.reflection_graph_dispatcher.dispatch_once()
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_new_messages_form_a_new_source_and_graph(runtime):
    first_segment = await _segment(runtime)
    first_run = await runtime.schedule_segment_reflection(first_segment.segment_id)
    assert await _dispatch_graph(runtime) == 4

    await runtime.submit_message(
        SubmitMessageCommand(
            account_id="local-player",
            conversation_id="xiaojin",
            player_text="后来又想起一件事",
            images=(),
            client_msg_id=uuid4(),
            local_timestamp=runtime.clock(),
        )
    )
    second_segment = await runtime.seal_unsegmented_messages(
        "local-player", "xiaojin", "xiaojin", now_utc=runtime.clock()
    )
    assert second_segment is not None
    assert (second_segment.first_message_sequence, second_segment.last_message_sequence) == (3, 3)
    assert second_segment.source_version != first_segment.source_version
    assert (
        await runtime.seal_unsegmented_messages(
            "local-player", "xiaojin", "xiaojin", now_utc=runtime.clock()
        )
        is None
    )

    second_run = await runtime.schedule_segment_reflection(second_segment.segment_id)
    assert second_run.graph_run.graph_run_id != first_run.graph_run.graph_run_id
    assert any(
        source.kind == "memory_segment"
        and source.ref == str(second_segment.segment_id)
        and source.version == second_segment.source_version
        for source in second_run.graph_run.source_scope.sources
    )
    assert await _dispatch_graph(runtime) >= 2
    stored_second = await runtime.reflection_graph_runs.get(second_run.graph_run.graph_run_id)
    assert stored_second is not None and stored_second.status.value == "completed"
    stored_first = await runtime.reflection_graph_runs.get(first_run.graph_run.graph_run_id)
    assert stored_first is not None and stored_first.status.value == "completed"
    assert (
        len(await runtime.memory_segments.list_for_scope("local-player", "xiaojin", "xiaojin")) == 2
    )


@pytest.mark.asyncio
async def test_sealing_keeps_a_multi_bubble_reply_in_one_segment(runtime):
    runtime.bubble_projector = lambda _proposal: ("第一句回复", "第二句回复")
    runtime.clock.current += timedelta(seconds=1)
    await runtime.submit_message(
        SubmitMessageCommand(
            account_id="local-player",
            conversation_id="xiaojin",
            player_text="再说一件事",
            images=(),
            client_msg_id=uuid4(),
            local_timestamp=runtime.clock(),
        )
    )
    runtime.clock.current += timedelta(seconds=6)
    assert await ConversationWorker(runtime).run_once()
    messages = await runtime.runtime_messages.list_conversation("local-player", "xiaojin")
    assert [message.message_sequence for message in messages] == [1, 2, 3, 4, 5]
    assert messages[3].result_id == messages[4].result_id

    first = await runtime.seal_unsegmented_messages(
        "local-player", "xiaojin", "xiaojin", through_sequence=4, now_utc=runtime.clock()
    )
    assert first is not None
    assert (first.first_message_sequence, first.last_message_sequence) == (1, 3)
    second = await runtime.seal_unsegmented_messages(
        "local-player", "xiaojin", "xiaojin", now_utc=runtime.clock()
    )
    assert second is not None
    assert (second.first_message_sequence, second.last_message_sequence) == (4, 5)
    async with runtime.database.transaction() as connection:
        sources = await MemoryProvenanceRepository().segment_sources(
            str(second.segment_id), connection=connection
        )
    assert [source.kind.value for source in sources] == ["message", "message", "thought"]
    assert (
        await runtime.seal_unsegmented_messages(
            "local-player", "xiaojin", "xiaojin", now_utc=runtime.clock()
        )
        is None
    )


class NoFollowUpAgent(StubCharacterAgent):
    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        result = await super().run(invocation)
        if invocation.scope.node_key != "segment_summary_plan":
            return result
        assert result.output is not None
        action = result.output.action.model_copy(
            update={
                "follow_up": FollowUpDecision(
                    relationship_reflect=False,
                    state_reflect=False,
                )
            }
        )
        return result.model_copy(
            update={"output": result.output.model_copy(update={"action": action})}
        )


class CapturingAgent(StubCharacterAgent):
    def __init__(self) -> None:
        super().__init__()
        self.invocations: list[AgentInvocation] = []

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        self.invocations.append(invocation)
        return await super().run(invocation)


class MemoryOrganizationAgent(StubCharacterAgent):
    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        if invocation.identity.purpose.name != "REFLECTION":
            return await super().run(invocation)
        source_ref = invocation.context.source_refs[0]
        if invocation.scope.node_key == "page_compose":
            action = LongTermMemoryPageAction(
                pages=(
                    LongTermMemoryPageItem(
                        memory_kind="promise",
                        content="我答应下次告诉对方结果。",
                        subject_kind="entity",
                        subject_id="player",
                    ),
                    LongTermMemoryPageItem(
                        memory_kind="event",
                        content="我记得我们一起完成了一次重要的交流。",
                        subject_kind="entity",
                        subject_id="player",
                    ),
                ),
                evidence_refs=(source_ref,),
            )
        elif invocation.scope.node_key == "graph_extract":
            action = GraphExtractionAction(
                entities=(
                    GraphEntityAction(
                        entity_id="player",
                        entity_kind="person",
                        canonical_name="玩家",
                    ),
                    GraphEntityAction(
                        entity_id="conversation",
                        entity_kind="event",
                        canonical_name="重要交流",
                    ),
                ),
                edges=(
                    GraphEdgeAction(
                        from_entity_id="player",
                        to_entity_id="conversation",
                        edge_kind="participated_in",
                    ),
                ),
                evidence_refs=(source_ref,),
            )
        else:
            raise AssertionError(f"unexpected memory node: {invocation.scope.node_key}")
        return AgentRunResult(
            invocation_id=invocation.identity.invocation_id,
            agent_id=invocation.identity.agent_id,
            agent_kind=invocation.identity.agent_kind,
            harness_version=self.harness_version,
            model_profile=self.model_profile,
            status=AgentRunStatus.COMPLETED,
            stop_reason=AgentStopReason.PROPOSAL_READY,
            output=ReflectionNodeOutput(contract=invocation.output_contract, action=action),
        )


class RelationshipFailureAgent(StubCharacterAgent):
    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        if invocation.scope.node_key == "relationship_reflect":
            return AgentRunResult(
                invocation_id=invocation.identity.invocation_id,
                agent_id=invocation.identity.agent_id,
                agent_kind=invocation.identity.agent_kind,
                harness_version=self.harness_version,
                model_profile=self.model_profile,
                status=AgentRunStatus.FAILED,
                stop_reason=AgentStopReason.TOOL_ERROR,
            )
        return await super().run(invocation)


@pytest.mark.asyncio
async def test_reflection_invocation_allows_one_model_repair(runtime):
    agent = CapturingAgent()
    runtime.agent = agent
    segment = await _segment(runtime)
    await runtime.schedule_segment_reflection(segment.segment_id)

    assert await _dispatch_graph(runtime) == 4
    assert agent.invocations
    assert {invocation.execution_policy.max_model_steps for invocation in agent.invocations} == {
        runtime.settings.reflection_max_model_steps
    }
    assert {invocation.execution_policy.max_model_requests for invocation in agent.invocations} == {
        runtime.settings.reflection_max_model_requests
    }


@pytest.mark.asyncio
async def test_optional_node_failure_keeps_available_reflection_result(runtime):
    runtime.agent = RelationshipFailureAgent()
    segment = await _segment(runtime)
    started = await runtime.schedule_segment_reflection(segment.segment_id)

    assert await _dispatch_graph(runtime) == 4
    run = await runtime.reflection_graph_runs.get(started.graph_run.graph_run_id)
    assert run is not None and run.status.value == "partial"
    tasks = await runtime.reflection_graph_nodes.list_for_graph(run.graph_run_id)
    status_by_key = {task.node_key: task.status.value for task in tasks}
    assert status_by_key == {
        "segment_summary_plan": "completed",
        "relationship_reflect": "failed",
        "state_reflect": "completed",
        "segment_aggregate": "completed",
    }
    result = await runtime.reflection_graph_results.get_for_graph(run.graph_run_id)
    assert result is not None and result.status.value == "approved"
    payload = json.loads(result.payload_json)
    assert payload["partial_failures"] == [
        {
            "node_key": "relationship_reflect",
            "error_code": "tool_error",
            "attempt_count": 1,
        }
    ]
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM relation_evidence WHERE source_kind = 'reflection'"
        )
    )["count"] == 0
    assert await runtime.character_state_entries.list_latest_for_character("xiaojin")
    await runtime.flush_trace_outbox()
    view = await runtime.reflection_run_view.get(run.graph_run_id)
    assert view is not None
    assert "reflection_graph.partial" in {trace.kind for trace in view.traces}


@pytest.mark.asyncio
async def test_graph_materializes_conditional_nodes_from_summary_action(runtime):
    runtime.agent = NoFollowUpAgent()
    segment = await _segment(runtime)
    started = await runtime.schedule_segment_reflection(segment.segment_id)

    assert await _dispatch_graph(runtime) == 2
    tasks = await runtime.reflection_graph_nodes.list_for_graph(started.graph_run.graph_run_id)
    status_by_key = {task.node_key: task.status.value for task in tasks}
    assert status_by_key["segment_summary_plan"] == "completed"
    assert status_by_key["relationship_reflect"] == "skipped"
    assert status_by_key["state_reflect"] == "skipped"
    assert status_by_key["segment_aggregate"] == "completed"


class RetryOnceAgent(StubCharacterAgent):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        self.calls += 1
        if self.calls == 1:
            return AgentRunResult(
                invocation_id=invocation.identity.invocation_id,
                agent_id=invocation.identity.agent_id,
                agent_kind=invocation.identity.agent_kind,
                harness_version="test",
                model_profile="test",
                status=AgentRunStatus.RETRYABLE,
                stop_reason=AgentStopReason.MODEL_ERROR,
            )
        return await super().run(invocation)


@pytest.mark.asyncio
async def test_failed_graph_can_be_reactivated_from_the_same_segment(runtime):
    runtime.agent = RetryOnceAgent()
    segment = await _segment(runtime)
    started = await runtime.schedule_segment_reflection(segment.segment_id)

    assert await runtime.reflection_graph_dispatcher.dispatch_once()
    failed_once = await runtime.reflection_graph_nodes.get_for_graph_node(
        started.graph_run.graph_run_id,
        "segment_summary_plan",
    )
    assert failed_once is not None and failed_once.status.value == "retry_wait"
    runtime.clock.current = failed_once.available_at_utc
    assert await _dispatch_graph(runtime) == 4

    completed = await runtime.reflection_graph_runs.get(started.graph_run.graph_run_id)
    assert completed is not None and completed.status.value == "completed"
    assert completed.execution_generation == 1


class AlwaysFailAgent(StubCharacterAgent):
    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        return AgentRunResult(
            invocation_id=invocation.identity.invocation_id,
            agent_id=invocation.identity.agent_id,
            agent_kind=invocation.identity.agent_kind,
            harness_version="test",
            model_profile="test",
            status=AgentRunStatus.RETRYABLE,
            stop_reason=AgentStopReason.MODEL_ERROR,
        )


class TerminalFailAgent(StubCharacterAgent):
    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        return AgentRunResult(
            invocation_id=invocation.identity.invocation_id,
            agent_id=invocation.identity.agent_id,
            agent_kind=invocation.identity.agent_kind,
            harness_version="test",
            model_profile="test",
            status=AgentRunStatus.FAILED,
            stop_reason=AgentStopReason.TOOL_ERROR,
        )


@pytest.mark.asyncio
async def test_memory_organization_writes_pages_entities_edges_and_consumption(runtime):
    segment = await _segment(runtime)
    await runtime.schedule_segment_reflection(segment.segment_id)
    assert await _dispatch_graph(runtime) == 4

    runtime.agent = MemoryOrganizationAgent()
    started = await runtime.schedule_memory_organization(
        MemoryOrganizationTrigger(
            account_id="local-player",
            conversation_id="xiaojin",
            character_id="xiaojin",
            through_sequence=segment.last_message_sequence,
            limit=16,
        )
    )
    assert started is not None
    assert started.graph_run.graph_kind.value == "memory_organize"
    assert await _dispatch_graph(runtime) == 3

    completed = await runtime.reflection_graph_runs.get(started.graph_run.graph_run_id)
    assert completed is not None and completed.status.value == "completed"
    result = await runtime.reflection_graph_results.get_for_graph(completed.graph_run_id)
    assert result is not None and result.status.value == "approved"

    memories = await runtime.memory_entries.list_for_scope("local-player", "xiaojin")
    assert {
        "我答应下次告诉对方结果。",
        "我记得我们一起完成了一次重要的交流。",
    } <= {item.content for item in memories}
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM memory_entities WHERE account_id=? AND character_id=?",
            ("local-player", "xiaojin"),
        )
    )["count"] == 2
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM memory_edges WHERE account_id=? AND character_id=?",
            ("local-player", "xiaojin"),
        )
    )["count"] == 1
    consumed = await runtime.database.fetchone(
        "SELECT outcome FROM memory_organization_consumption WHERE segment_id=?",
        (str(segment.segment_id),),
    )
    assert consumed is not None and consumed["outcome"] == "completed"
    assert (
        await runtime.schedule_memory_organization(
            MemoryOrganizationTrigger(
                account_id="local-player",
                conversation_id="xiaojin",
                character_id="xiaojin",
                through_sequence=segment.last_message_sequence,
                limit=16,
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_continuity_compression_writes_digest_and_advances_coverage(runtime):
    segment = await _segment(runtime)
    await runtime.schedule_segment_reflection(segment.segment_id)
    assert await _dispatch_graph(runtime) == 4

    started = await runtime.schedule_continuity_compression(
        ContinuityCompressionTrigger(
            account_id="local-player",
            conversation_id="xiaojin",
            character_id="xiaojin",
            through_sequence=segment.last_message_sequence,
            limit=16,
        )
    )
    assert started is not None
    assert started.graph_run.graph_kind.value == "continuity_compress"
    assert await _dispatch_graph(runtime) == 2

    completed = await runtime.reflection_graph_runs.get(started.graph_run.graph_run_id)
    assert completed is not None and completed.status.value == "completed"
    result = await runtime.reflection_graph_results.get_for_graph(completed.graph_run_id)
    assert result is not None and result.status.value == "approved"

    digest = await runtime.database.fetchone("SELECT * FROM conversation_digests")
    assert digest is not None
    assert digest["content"] == "最近的交流保持着连续的陪伴感。"
    assert digest["previous_digest_id"] is None
    assert digest["covers_through_sequence"] == segment.last_message_sequence
    assert (
        await runtime.schedule_continuity_compression(
            ContinuityCompressionTrigger(
                account_id="local-player",
                conversation_id="xiaojin",
                character_id="xiaojin",
                through_sequence=segment.last_message_sequence,
                limit=16,
            )
        )
        is None
    )

    runtime.clock.current = runtime.clock() + timedelta(seconds=6)
    await runtime.submit_message(
        SubmitMessageCommand(
            account_id="local-player",
            conversation_id="xiaojin",
            player_text="我们继续聊聊刚才的事情。",
            images=(),
            client_msg_id=uuid4(),
            local_timestamp=runtime.clock(),
        )
    )
    runtime.clock.current = runtime.clock() + timedelta(seconds=6)
    assert await ConversationWorker(runtime).run_once()
    second_segment = await runtime.seal_unsegmented_messages(
        "local-player", "xiaojin", "xiaojin", now_utc=runtime.clock()
    )
    assert second_segment is not None
    await runtime.schedule_segment_reflection(second_segment.segment_id)
    assert await _dispatch_graph(runtime) == 4
    first_digest = await runtime.database.fetchone(
        "SELECT * FROM conversation_digests ORDER BY covers_through_sequence LIMIT 1"
    )
    assert first_digest is not None
    async with runtime.database.transaction(immediate=True) as connection:
        too_small = await MemoryProvenanceRepository().freeze_batch(
            "local-player",
            "xiaojin",
            "xiaojin",
            through_sequence=second_segment.last_message_sequence,
            now_utc=runtime.clock(),
            connection=connection,
            max_material_chars=len(first_digest["content"]),
        )
    assert too_small is None

    second_started = await runtime.schedule_continuity_compression(
        ContinuityCompressionTrigger(
            account_id="local-player",
            conversation_id="xiaojin",
            character_id="xiaojin",
            through_sequence=second_segment.last_message_sequence,
            limit=16,
        )
    )
    assert second_started is not None
    second_materials = second_started.snapshot_build.snapshot.context.materials
    assert second_materials[0].source_kind == "conversation_digest"
    assert second_materials[1].source_kind == "memory_segment_summary"
    assert await _dispatch_graph(runtime) == 2
    digests = await runtime.database.fetchall(
        "SELECT * FROM conversation_digests ORDER BY covers_through_sequence"
    )
    assert len(digests) == 2
    assert digests[1]["previous_digest_id"] == digests[0]["digest_id"]
    assert digests[1]["covers_through_sequence"] == second_segment.last_message_sequence


@pytest.mark.asyncio
async def test_same_source_reactivates_a_failed_graph(runtime):
    runtime.agent = AlwaysFailAgent()
    segment = await _segment(runtime)
    started = await runtime.schedule_segment_reflection(segment.segment_id)
    for _ in range(runtime.settings.max_agent_attempts):
        assert await runtime.reflection_graph_dispatcher.dispatch_once()
        root = await runtime.reflection_graph_nodes.get_for_graph_node(
            started.graph_run.graph_run_id,
            "segment_summary_plan",
        )
        assert root is not None
        if root.status.value == "retry_wait":
            runtime.clock.current = root.available_at_utc

    failed = await runtime.reflection_graph_runs.get(started.graph_run.graph_run_id)
    assert failed is not None and failed.status.value == "failed"
    assert (
        await runtime.memory_segments.get(segment.segment_id)
    ).status is MemorySegmentStatus.SEALED
    assert not await runtime.database.fetchall(
        "SELECT 1 FROM memory_source_coverage WHERE owner_kind = 'segment_summary' "
        "AND owner_id = ?",
        (str(segment.segment_id),),
    )
    runtime.agent = StubCharacterAgent()
    restarted = await runtime.schedule_segment_reflection(segment.segment_id)

    assert restarted.graph_run.graph_run_id == failed.graph_run_id
    assert restarted.graph_run.status.value == "running"
    assert restarted.graph_run.execution_generation == 2
    root = await runtime.reflection_graph_nodes.get_for_graph_node(
        failed.graph_run_id,
        "segment_summary_plan",
    )
    assert root is not None and root.status.value == "pending"
    assert await _dispatch_graph(runtime) == 4
    completed = await runtime.reflection_graph_runs.get(failed.graph_run_id)
    assert completed is not None and completed.status.value == "completed"
    assert completed.execution_generation == 2
    assert (
        await runtime.memory_segments.get(segment.segment_id)
    ).status is MemorySegmentStatus.INGESTED


@pytest.mark.asyncio
async def test_non_retryable_agent_run_fails_reflection_graph(runtime):
    runtime.agent = TerminalFailAgent()
    segment = await _segment(runtime)
    started = await runtime.schedule_segment_reflection(segment.segment_id)

    assert await runtime.reflection_graph_dispatcher.dispatch_once()

    root = await runtime.reflection_graph_nodes.get_for_graph_node(
        started.graph_run.graph_run_id,
        "segment_summary_plan",
    )
    assert root is not None and root.status.value == "failed"
    failed = await runtime.reflection_graph_runs.get(started.graph_run.graph_run_id)
    assert failed is not None and failed.status.value == "failed"
