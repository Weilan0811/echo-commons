from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from support_faults import MutableClock

from echo_server.agents.contracts import (
    AgentInvocation,
    AgentRunResult,
    AgentRunStatus,
    AgentStopReason,
    CharacterMessageProposal,
    FailureCategory,
    FailureInfo,
    InvocationOrigin,
    OutputContractRef,
    ProposalEnvelope,
    ProposalKind,
    ProposalOutput,
    RecoveryAction,
)
from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.domain.character_state_entry import CharacterStateEntry, CharacterStateKind
from echo_server.domain.conversation import ConversationParticipant
from echo_server.domain.messages import SubmitMessageCommand
from echo_server.domain.relationship import (
    RelationshipEvidence,
    RelationshipKey,
    RelationshipState,
    RelationshipTargetKind,
    RelationshipType,
    RelationshipValues,
)
from echo_server.domain.state import (
    CharacterAvailabilityStatus,
    CharacterState,
    WorldState,
)
from echo_server.runtime.application_runtime import ApplicationRuntime
from echo_server.runtime.conversation_worker import ConversationWorker
from echo_server.services.model_gateway import TaskRouting
from echo_server.store.database import Database

BASE_TIME = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


class NoProposalAgent:
    agent_id = "no-proposal-agent"
    agent_kind = "character"
    model_profile = "stub"
    harness_version = "stub-v1"

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        return AgentRunResult(
            invocation_id=invocation.identity.invocation_id,
            agent_id=self.agent_id,
            agent_kind=self.agent_kind,
            harness_version=self.harness_version,
            model_profile=self.model_profile,
            status=AgentRunStatus.NO_PROPOSAL,
            stop_reason=AgentStopReason.NO_MOTIVATION,
        )


class RecoveryResultAgent:
    agent_id = "recovery-result-agent"
    agent_kind = "character"
    model_profile = "stub"
    harness_version = "stub-v1"

    def __init__(
        self,
        *,
        status: AgentRunStatus,
        action: RecoveryAction,
        code: str,
    ) -> None:
        self.status = status
        self.recovery = FailureInfo(
            code=code,
            category=FailureCategory.TOOL,
            action=action,
            retryable=action is RecoveryAction.RETRY_TASK,
        )

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        return AgentRunResult(
            invocation_id=invocation.identity.invocation_id,
            agent_id=self.agent_id,
            agent_kind=self.agent_kind,
            harness_version=self.harness_version,
            model_profile=self.model_profile,
            status=self.status,
            stop_reason=AgentStopReason.TOOL_ERROR,
            recovery=self.recovery,
        )


class CapturingAgent(StubCharacterAgent):
    def __init__(self) -> None:
        super().__init__()
        self.invocations: list[AgentInvocation] = []

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        self.invocations.append(invocation)
        return await super().run(invocation)


class DowngradedCapturingAgent(CapturingAgent):
    model_profile = "strong"

    def __init__(self) -> None:
        super().__init__()
        self.routing = TaskRouting(
            default_profile="strong",
            task_profiles={"conversation.reply": "strong"},
            strong_enabled=False,
        )

    def route_for(self, task_kind: str):
        return self.routing.route_for(task_kind)

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        result = await super().run(invocation)
        return result.model_copy(
            update={"model_profile": invocation.execution_policy.model_profile}
        )


class WrongCharacterAgent:
    agent_id = "wrong-character-agent"
    agent_kind = "character"
    model_profile = "stub"
    harness_version = "stub-v1"

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        proposal = ProposalEnvelope(
            proposal_id=uuid4(),
            kind=ProposalKind.CHARACTER_MESSAGE,
            origin=InvocationOrigin(invocation_id=invocation.identity.invocation_id),
            payload=CharacterMessageProposal(
                character_id="not-the-participant",
                thought="我不该回应这个对象。",
                utterance="invalid target",
            ),
        )
        return AgentRunResult(
            invocation_id=invocation.identity.invocation_id,
            agent_id=self.agent_id,
            agent_kind=self.agent_kind,
            harness_version=self.harness_version,
            model_profile=self.model_profile,
            status=AgentRunStatus.COMPLETED,
            stop_reason=AgentStopReason.PROPOSAL_READY,
            output=ProposalOutput(
                contract=OutputContractRef(kind="character_message", version="v2"),
                proposal=proposal,
            ),
        )


@pytest_asyncio.fixture
async def t3_runtime(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
        max_agent_attempts=2,
        retry_backoff_seconds=0,
    )
    clock = MutableClock(BASE_TIME)
    runtime = ApplicationRuntime(
        Database(settings.database_path),
        StubCharacterAgent(),
        settings,
        clock=clock,
        worker_id="t3-test-worker",
    )
    await runtime.start()
    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.world_states.save(
            WorldState(
                state_version=0,
                world_time_utc=clock.current,
                updated_at_utc=clock.current,
            ),
            connection=connection,
        )
        await runtime.character_states.save(
            CharacterState(
                character_id=runtime.settings.default_character_id,
                availability_status=CharacterAvailabilityStatus.AVAILABLE,
                state_version=0,
                updated_at_utc=clock.current,
            ),
            connection=connection,
        )
        await runtime.participants.save(
            ConversationParticipant(
                conversation_id=runtime.settings.default_conversation_id,
                character_id=runtime.settings.default_character_id,
                joined_at_utc=clock.current,
            ),
            account_id=runtime.settings.account_id,
            connection=connection,
        )
    yield runtime, clock
    if runtime.database.is_open:
        await runtime.stop()


async def submit(runtime: ApplicationRuntime, text: str = "hello") -> UUID:
    receipt = await runtime.submit_message(
        SubmitMessageCommand(
            account_id=runtime.settings.account_id,
            conversation_id=runtime.settings.default_conversation_id,
            player_text=text,
            images=(),
            client_msg_id=uuid4(),
            local_timestamp=BASE_TIME,
        )
    )
    return receipt.message_id


async def claim_one(runtime: ApplicationRuntime, clock: MutableClock):
    clock.current = BASE_TIME + timedelta(seconds=6)
    task = await runtime.prepare_next_task()
    assert task is not None
    claimed = await runtime.runtime_tasks.claim_next(
        worker_id=runtime.worker_id,
        now_utc=clock.current,
        lease_seconds=30,
        account_id=runtime.settings.account_id,
        conversation_id=runtime.settings.default_conversation_id,
    )
    assert claimed is not None
    return claimed


@pytest.mark.asyncio
async def test_t3_approves_result_writes_character_message_and_covers_task(t3_runtime):
    runtime, clock = t3_runtime
    await submit(runtime, "hello")
    task = await claim_one(runtime, clock)

    assert await runtime.execution.run_task(task.task_id)

    stored_task = await runtime.runtime_tasks.get(task.task_id)
    assert stored_task is not None
    assert stored_task.status.value == "completed"
    result = await runtime.database.fetchone(
        "SELECT result_id, status, decision_code, payload_json "
        "FROM agent_results WHERE task_id = ?",
        (str(task.task_id),),
    )
    assert result["status"] == "approved"
    assert result["decision_code"] == "approved"
    result_payload = json.loads(result["payload_json"])
    assert result_payload["kind"] == "character_message"
    assert result_payload["payload"]["utterance"] == "我在听。"
    assert "thought" not in result_payload["payload"]
    message = await runtime.database.fetchone(
        "SELECT sender_type, text, result_id, bubble_index FROM messages "
        "WHERE sender_type = 'character'"
    )
    assert message["sender_type"] == "character"
    assert message["text"] == "我在听。"
    assert message["result_id"]
    assert message["bubble_index"] == 0
    thought = await runtime.thoughts.get_by_result(UUID(message["result_id"]))
    assert thought is not None
    assert thought.account_id == runtime.settings.account_id
    assert thought.character_id == runtime.settings.default_character_id
    assert thought.game_day == "2026-09-06"
    assert thought.content == "我先接住对方的话。"
    await runtime.flush_trace_outbox()
    trace_rows = await runtime.database.fetchall("SELECT payload_json FROM traces")
    assert all("我先接住对方的话。" not in row["payload_json"] for row in trace_rows)
    assert (
        await runtime.database.fetchone(
            "SELECT status FROM input_batches WHERE task_id = ?",
            (str(task.task_id),),
        )
    )["status"] == "covered"
    assert clock.current == BASE_TIME + timedelta(seconds=6)


@pytest.mark.asyncio
async def test_t3_uses_task_route_and_records_explicit_strong_downgrade(t3_runtime):
    runtime, clock = t3_runtime
    agent = DowngradedCapturingAgent()
    runtime.agent = agent
    await submit(runtime, "route check")
    task = await claim_one(runtime, clock)

    assert await runtime.execution.run_task(task.task_id)
    assert len(agent.invocations) == 1
    assert agent.invocations[0].execution_policy.model_profile == "light"

    await runtime.flush_trace_outbox()
    row = await runtime.database.fetchone(
        """
        SELECT payload_json
        FROM traces
        WHERE kind = 'agent.completed' AND entity_id = ?
        ORDER BY created_at_utc DESC
        LIMIT 1
        """,
        (str(task.task_id),),
    )
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["task_kind"] == "conversation.reply"
    assert payload["requested_model_profile"] == "strong"
    assert payload["model_profile"] == "light"
    assert payload["route_fallback"] == "strong_disabled"


@pytest.mark.asyncio
async def test_t3_no_proposal_completes_without_fabricating_message(t3_runtime):
    runtime, clock = t3_runtime
    runtime.agent = NoProposalAgent()
    await submit(runtime)
    task = await claim_one(runtime, clock)

    assert await runtime.execution.run_task(task.task_id)

    result = await runtime.database.fetchone(
        "SELECT result_kind, status, decision_code FROM agent_results WHERE task_id = ?",
        (str(task.task_id),),
    )
    assert dict(result) == {
        "result_kind": "no_proposal",
        "status": "approved",
        "decision_code": "no_proposal",
    }
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM messages WHERE sender_type = 'character'"
        )
    )["count"] == 0
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM thoughts"))["count"] == 0
    assert (await runtime.runtime_tasks.get(task.task_id)).status.value == "completed"


@pytest.mark.asyncio
async def test_t3_retryable_agent_result_schedules_task_retry(t3_runtime):
    runtime, clock = t3_runtime
    runtime.agent = RecoveryResultAgent(
        status=AgentRunStatus.RETRYABLE,
        action=RecoveryAction.RETRY_TASK,
        code="memory_search_failed",
    )
    await submit(runtime)
    task = await claim_one(runtime, clock)

    assert await runtime.execution.run_task(task.task_id)

    stored_task = await runtime.runtime_tasks.get(task.task_id)
    assert stored_task is not None
    assert stored_task.status.value == "retry_wait"
    assert stored_task.last_error_code == "memory_search_failed"
    assert (
        await runtime.database.fetchone(
            "SELECT status FROM input_batches WHERE task_id = ?",
            (str(task.task_id),),
        )
    )["status"] == "assigned"


@pytest.mark.asyncio
async def test_t3_non_retryable_agent_result_fails_task_immediately(t3_runtime):
    runtime, clock = t3_runtime
    runtime.agent = RecoveryResultAgent(
        status=AgentRunStatus.FAILED,
        action=RecoveryAction.FAIL,
        code="tool_not_allowed",
    )
    await submit(runtime)
    task = await claim_one(runtime, clock)

    assert await runtime.execution.run_task(task.task_id)

    stored_task = await runtime.runtime_tasks.get(task.task_id)
    assert stored_task is not None
    assert stored_task.status.value == "failed"
    assert stored_task.last_error_code == "tool_not_allowed"
    assert (
        await runtime.database.fetchone(
            "SELECT status FROM input_batches WHERE task_id = ?",
            (str(task.task_id),),
        )
    )["status"] == "terminal_failed"
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM messages WHERE sender_type = 'character'"
        )
    )["count"] == 0


@pytest.mark.asyncio
async def test_t3_rechecks_eligibility_and_defers_assigned_batches(t3_runtime):
    runtime, clock = t3_runtime
    await submit(runtime)
    task = await claim_one(runtime, clock)
    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.character_states.save(
            CharacterState(
                character_id=runtime.settings.default_character_id,
                availability_status=CharacterAvailabilityStatus.BUSY,
                state_version=1,
                updated_at_utc=clock.current,
                reason_code="story_event",
            ),
            connection=connection,
        )

    assert await runtime.execution.run_task(task.task_id)

    stored_task = await runtime.runtime_tasks.get(task.task_id)
    assert stored_task is not None
    assert stored_task.status.value == "deferred"
    assert (
        await runtime.database.fetchone(
            "SELECT status FROM agent_results WHERE task_id = ?",
            (str(task.task_id),),
        )
    )["status"] == "expired"
    assert (
        await runtime.database.fetchone(
            "SELECT status FROM input_batches WHERE task_id = ?",
            (str(task.task_id),),
        )
    )["status"] == "assigned"
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM messages WHERE sender_type = 'character'"
        )
    )["count"] == 0
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM thoughts"))["count"] == 0


@pytest.mark.asyncio
async def test_t3_resumes_deferred_task_after_eligibility_returns(t3_runtime):
    runtime, clock = t3_runtime
    await submit(runtime)
    task = await claim_one(runtime, clock)
    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.character_states.save(
            CharacterState(
                character_id=runtime.settings.default_character_id,
                availability_status=CharacterAvailabilityStatus.BUSY,
                state_version=1,
                updated_at_utc=clock.current,
            ),
            connection=connection,
        )

    assert await runtime.execution.run_task(task.task_id)
    deferred = await runtime.runtime_tasks.get(task.task_id)
    assert deferred is not None
    assert deferred.status.value == "deferred"

    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.character_states.save(
            CharacterState(
                character_id=runtime.settings.default_character_id,
                availability_status=CharacterAvailabilityStatus.AVAILABLE,
                state_version=2,
                updated_at_utc=clock.current,
            ),
            connection=connection,
        )

    worker = ConversationWorker(runtime)
    assert await worker.run_once()
    resumed = await runtime.runtime_tasks.get(task.task_id)
    assert resumed is not None
    assert resumed.status.value == "completed"
    assert resumed.attempt_count == 2
    result_statuses = await runtime.database.fetchall(
        "SELECT attempt_no, status FROM agent_results WHERE task_id = ? ORDER BY attempt_no",
        (str(task.task_id),),
    )
    assert [(row["attempt_no"], row["status"]) for row in result_statuses] == [
        (1, "expired"),
        (2, "approved"),
    ]


@pytest.mark.asyncio
async def test_t3_rejects_invalid_proposal_then_fails_after_retry_limit(t3_runtime):
    runtime, clock = t3_runtime
    runtime.agent = WrongCharacterAgent()
    await submit(runtime)
    task = await claim_one(runtime, clock)

    assert await runtime.execution.run_task(task.task_id)
    retrying = await runtime.runtime_tasks.get(task.task_id)
    assert retrying is not None
    assert retrying.status.value == "retry_wait"
    assert retrying.attempt_count == 1

    claimed_again = await runtime.runtime_tasks.claim_next(
        worker_id=runtime.worker_id,
        now_utc=clock.current,
        lease_seconds=30,
        account_id=runtime.settings.account_id,
        conversation_id=runtime.settings.default_conversation_id,
    )
    assert claimed_again is not None
    assert await runtime.execution.run_task(claimed_again.task_id)
    failed = await runtime.runtime_tasks.get(task.task_id)
    assert failed is not None
    assert failed.status.value == "failed"
    assert (
        await runtime.database.fetchone(
            "SELECT status FROM input_batches WHERE task_id = ?",
            (str(task.task_id),),
        )
    )["status"] == "terminal_failed"
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM messages WHERE sender_type = 'character'"
        )
    )["count"] == 0
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM thoughts"))["count"] == 0


@pytest.mark.asyncio
async def test_t3_supports_multiple_bubbles_with_result_level_idempotency(t3_runtime):
    runtime, clock = t3_runtime
    runtime.bubble_projector = lambda _: ("first bubble", "second bubble")
    await submit(runtime)
    task = await claim_one(runtime, clock)

    assert await runtime.execution.run_task(task.task_id)

    rows = await runtime.database.fetchall(
        "SELECT result_id, bubble_index, text FROM messages "
        "WHERE sender_type = 'character' ORDER BY bubble_index"
    )
    assert [(row["bubble_index"], row["text"]) for row in rows] == [
        (0, "first bubble"),
        (1, "second bubble"),
    ]
    assert rows[0]["result_id"] == rows[1]["result_id"]
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM thoughts"))["count"] == 1


@pytest.mark.asyncio
async def test_t3_does_not_commit_a_late_result_after_lease_expiry(t3_runtime):
    runtime, clock = t3_runtime
    await submit(runtime)
    clock.current = BASE_TIME + timedelta(seconds=6)
    task = await runtime.prepare_next_task()
    assert task is not None
    claimed = await runtime.runtime_tasks.claim_next(
        worker_id=runtime.worker_id,
        now_utc=clock.current,
        lease_seconds=1,
        account_id=runtime.settings.account_id,
        conversation_id=runtime.settings.default_conversation_id,
    )
    assert claimed is not None
    clock.current += timedelta(seconds=2)

    assert await runtime.execution.run_task(task.task_id)

    stored_task = await runtime.runtime_tasks.get(task.task_id)
    assert stored_task is not None
    assert stored_task.status.value == "processing"
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM agent_results WHERE task_id = ?",
            (str(task.task_id),),
        )
    )["count"] == 0
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM messages WHERE sender_type = 'character'"
        )
    )["count"] == 0
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM thoughts"))["count"] == 0
    async with runtime.database.transaction(immediate=True) as connection:
        assert (
            await runtime.runtime_tasks.recover_expired(
                clock.current,
                connection=connection,
            )
            == 1
        )
    recovered = await runtime.runtime_tasks.get(task.task_id)
    assert recovered is not None
    assert recovered.status.value == "retry_wait"


@pytest.mark.asyncio
async def test_t3_restarts_and_recovers_an_expired_task_lease(t3_runtime):
    runtime, clock = t3_runtime
    await submit(runtime)
    task = await claim_one(runtime, clock)
    clock.current += timedelta(seconds=31)
    await runtime.stop()

    restarted = ApplicationRuntime(
        Database(runtime.settings.database_path),
        StubCharacterAgent({"xiaojin": "restarted"}),
        runtime.settings,
        clock=clock,
        worker_id="restarted-worker",
    )
    await restarted.start()
    recovered = await restarted.runtime_tasks.get(task.task_id)
    assert recovered is not None
    assert recovered.status.value == "retry_wait"

    worker = ConversationWorker(restarted)
    assert await worker.run_once()
    completed = await restarted.runtime_tasks.get(task.task_id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert (
        await restarted.database.fetchone(
            "SELECT text FROM messages WHERE sender_type = 'character'"
        )
    )["text"] == "restarted"
    await restarted.stop()


@pytest.mark.asyncio
async def test_t3_rolls_back_result_message_and_task_completion_on_message_failure(
    t3_runtime, monkeypatch
):
    runtime, clock = t3_runtime
    await submit(runtime)
    task = await claim_one(runtime, clock)

    async def fail_insert(*args, **kwargs):
        raise RuntimeError("message insert failed")

    monkeypatch.setattr(runtime.runtime_messages, "insert", fail_insert)

    assert await runtime.execution.run_task(task.task_id)

    stored_task = await runtime.runtime_tasks.get(task.task_id)
    assert stored_task is not None
    assert stored_task.status.value == "processing"
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM agent_results WHERE task_id = ?",
            (str(task.task_id),),
        )
    )["count"] == 0
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM messages WHERE sender_type = 'character'"
        )
    )["count"] == 0
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM thoughts"))["count"] == 0


@pytest.mark.asyncio
async def test_t3_snapshot_excludes_messages_after_frozen_input(t3_runtime):
    runtime, clock = t3_runtime
    capturing_agent = CapturingAgent()
    runtime.agent = capturing_agent
    await submit(runtime, "first")
    task = await claim_one(runtime, clock)
    clock.current += timedelta(seconds=1)
    await submit(runtime, "later")

    assert await runtime.execution.run_task(task.task_id)

    assert len(capturing_agent.invocations) == 1
    invocation = capturing_agent.invocations[0]
    assert [message.text for message in invocation.context.input_messages] == ["first"]
    assert [message.text for message in invocation.context.recent_messages] == []
    assert invocation.context.baseline_resource_id == runtime.identity_catalog.baseline.resource_id
    assert invocation.context.baseline_content == runtime.identity_catalog.baseline.content
    assert invocation.context.baseline_version == runtime.identity_catalog.baseline.version
    assert invocation.context.identity_resource_id == "xiaojin"
    assert invocation.context.identity_content == (
        runtime.identity_catalog.character("xiaojin").content
    )
    assert invocation.context.identity_version == "0.5.0-draft"
    assert invocation.context.snapshot_version == 2
    assert invocation.context.request.conversation_id == runtime.settings.default_conversation_id
    assert invocation.context.identity.profile_resource_id == "xiaojin.profile"
    assert invocation.context.identity.relational_dynamics_resource_id == (
        "xiaojin.relational-dynamics"
    )
    assert invocation.context.character_state.character_id == "xiaojin"
    assert invocation.context.character_state.availability_version == 0
    assert invocation.context.relationship_state.subject_id == runtime.settings.account_id
    assert invocation.context.relationship_state.relationship_type == "stranger"
    assert invocation.context.relationship_state.affection is None
    assert invocation.context.relationship_state.trust is None
    assert invocation.context.relationship_state.attachment is None
    assert invocation.context.situation.world_time_utc == BASE_TIME
    assert {(item.source, item.version) for item in invocation.context.source_versions} >= {
        ("conversation", task.context_version),
        ("identity.bundle", "0.5.0-draft"),
        ("world_state", "0"),
        ("character_state.physical", "0"),
        ("character_state.mood", "0"),
        ("character_state.activity", "0"),
        ("relationship_state", "0"),
    }
    assert invocation.context.prompt_layout_version == 8
    assert invocation.correlation.task_id == task.task_id


@pytest.mark.asyncio
async def test_t3_snapshot_reads_use_one_read_transaction(t3_runtime, monkeypatch):
    runtime, clock = t3_runtime
    capturing_agent = CapturingAgent()
    runtime.agent = capturing_agent
    await submit(runtime, "snapshot")
    task = await claim_one(runtime, clock)

    connections = []

    original_conversation_get = runtime.snapshot_builder.conversations.get
    original_batch_list = runtime.snapshot_builder.input_batches.list_for_task
    original_input_message_list = runtime.snapshot_builder.messages.list_for_input_batches
    original_recent_message_list = runtime.snapshot_builder.messages.list_conversation_through
    original_world_state_get = runtime.world_states.get
    original_availability_get = runtime.character_states.get
    original_self_state_list = runtime.character_state_entries.list_latest_for_character
    original_relationship_get = runtime.relationship_states.get

    async def capture_conversation(*args, **kwargs):
        connections.append(kwargs.get("connection"))
        return await original_conversation_get(*args, **kwargs)

    async def capture_batches(*args, **kwargs):
        connections.append(kwargs.get("connection"))
        return await original_batch_list(*args, **kwargs)

    async def capture_input_messages(*args, **kwargs):
        connections.append(kwargs.get("connection"))
        return await original_input_message_list(*args, **kwargs)

    async def capture_recent_messages(*args, **kwargs):
        connections.append(kwargs.get("connection"))
        return await original_recent_message_list(*args, **kwargs)

    async def capture_world_state(*args, **kwargs):
        connections.append(kwargs.get("connection"))
        return await original_world_state_get(*args, **kwargs)

    async def capture_availability(*args, **kwargs):
        connections.append(kwargs.get("connection"))
        return await original_availability_get(*args, **kwargs)

    async def capture_self_state(*args, **kwargs):
        connections.append(kwargs.get("connection"))
        return await original_self_state_list(*args, **kwargs)

    async def capture_relationship(*args, **kwargs):
        connections.append(kwargs.get("connection"))
        return await original_relationship_get(*args, **kwargs)

    monkeypatch.setattr(runtime.snapshot_builder.conversations, "get", capture_conversation)
    monkeypatch.setattr(runtime.snapshot_builder.input_batches, "list_for_task", capture_batches)
    monkeypatch.setattr(
        runtime.snapshot_builder.messages,
        "list_for_input_batches",
        capture_input_messages,
    )
    monkeypatch.setattr(
        runtime.snapshot_builder.messages,
        "list_conversation_through",
        capture_recent_messages,
    )
    monkeypatch.setattr(runtime.world_states, "get", capture_world_state)
    monkeypatch.setattr(runtime.character_states, "get", capture_availability)
    monkeypatch.setattr(
        runtime.character_state_entries,
        "list_latest_for_character",
        capture_self_state,
    )
    monkeypatch.setattr(runtime.relationship_states, "get", capture_relationship)

    assert await runtime.execution.run_task(task.task_id)
    snapshot_connections = connections[:8]
    assert len(snapshot_connections) == 8
    assert all(connection is not None for connection in snapshot_connections)
    assert len({id(connection) for connection in snapshot_connections}) == 1
    assert len(capturing_agent.invocations) == 1


@pytest.mark.asyncio
async def test_t3_context_projects_latest_self_state_and_directed_relationship(t3_runtime):
    runtime, clock = t3_runtime
    character_id = runtime.settings.default_character_id
    account_id = runtime.settings.account_id
    previous_physical = CharacterStateEntry(
        entry_id=uuid4(),
        character_id=character_id,
        state_kind=CharacterStateKind.PHYSICAL,
        value="之前身体状态不错",
        source_kind="test",
        source_ref="physical-old",
        state_version=1,
        recorded_at_utc=BASE_TIME - timedelta(hours=1),
    )
    expired_physical = CharacterStateEntry(
        entry_id=uuid4(),
        character_id=character_id,
        state_kind=CharacterStateKind.PHYSICAL,
        value="刚才有些疲惫",
        source_kind="test",
        source_ref="physical-current",
        state_version=2,
        recorded_at_utc=BASE_TIME - timedelta(minutes=1),
        expires_at_utc=BASE_TIME + timedelta(seconds=1),
    )
    mood = CharacterStateEntry(
        entry_id=uuid4(),
        character_id=character_id,
        state_kind=CharacterStateKind.MOOD,
        value="有点想安静一会儿",
        source_kind="test",
        source_ref="mood-current",
        state_version=1,
        recorded_at_utc=BASE_TIME,
    )
    activity = CharacterStateEntry(
        entry_id=uuid4(),
        character_id=character_id,
        state_kind=CharacterStateKind.ACTIVITY,
        value="正在修改一幅画",
        source_kind="test",
        source_ref="activity-current",
        state_version=1,
        recorded_at_utc=BASE_TIME,
        expires_at_utc=BASE_TIME + timedelta(hours=1),
    )
    relationship_key = RelationshipKey(
        account_id=account_id,
        observer_character_id=character_id,
        target_kind=RelationshipTargetKind.ACCOUNT,
        target_id=account_id,
    )
    evidence = RelationshipEvidence(
        evidence_id=uuid4(),
        key=relationship_key,
        evidence_kind="interaction",
        source_kind="message",
        source_ref="source-message-1",
        occurred_at_utc=BASE_TIME,
        recorded_at_utc=BASE_TIME,
    )
    relationship = RelationshipState(
        key=relationship_key,
        relationship_type=RelationshipType.ACQUAINTANCE,
        values=RelationshipValues(affection=32, trust=26, attachment=4),
        state_version=1,
        updated_at_utc=BASE_TIME,
        attitude_summary="愿意继续听对方说说近况",
        attitude_source_refs=(evidence.evidence_id,),
    )
    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.character_state_entries.append(
            previous_physical,
            expected_version=0,
            connection=connection,
        )
        await runtime.character_state_entries.append(
            expired_physical,
            expected_version=1,
            connection=connection,
        )
        await runtime.character_state_entries.append(
            mood,
            expected_version=0,
            connection=connection,
        )
        await runtime.character_state_entries.append(
            activity,
            expected_version=0,
            connection=connection,
        )
        await runtime.relationship_evidence.append(evidence, connection=connection)
        await runtime.relationship_states.save(
            relationship,
            expected_version=0,
            connection=connection,
        )

    capturing_agent = CapturingAgent()
    runtime.agent = capturing_agent
    await submit(runtime, "你在做什么？")
    task = await claim_one(runtime, clock)

    assert await runtime.execution.run_task(task.task_id)
    assert len(capturing_agent.invocations) == 1
    context = capturing_agent.invocations[0].context
    assert context.character_state.physical_condition == ""
    assert context.character_state.mood == "有点想安静一会儿"
    assert context.character_state.current_activity == "正在修改一幅画"
    assert context.relationship_state.relationship_type == "acquaintance"
    assert context.relationship_state.affection == 32
    assert context.relationship_state.trust == 26
    assert context.relationship_state.attachment == 4
    assert context.relationship_state.attitude_summary == "愿意继续听对方说说近况"
    assert {(item.source, item.version) for item in context.source_versions} >= {
        ("character_availability", "0"),
        ("character_state.physical", "2"),
        ("character_state.mood", "1"),
        ("character_state.activity", "1"),
        ("relationship_state", "1"),
    }


@pytest.mark.asyncio
async def test_t3_trace_keeps_identity_metadata_without_prompt_content(t3_runtime):
    runtime, clock = t3_runtime
    await submit(runtime, "trace identity check")
    task = await claim_one(runtime, clock)

    assert await runtime.execution.run_task(task.task_id)
    await runtime.flush_trace_outbox()

    row = await runtime.database.fetchone(
        """
        SELECT payload_json
        FROM traces
        WHERE kind = 'agent.completed' AND entity_id = ?
        ORDER BY created_at_utc DESC
        LIMIT 1
        """,
        (str(task.task_id),),
    )
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["baseline_resource_id"] == "default-chat"
    assert payload["baseline_version"] == "0.6.1-draft"
    assert payload["identity_resource_id"] == "xiaojin"
    assert payload["identity_version"] == "0.5.0-draft"
    assert payload["prompt_layout_version"] == 8
    assert payload["output_schema"] == "character_message.v2"
    assert "trace identity check" not in row["payload_json"]
