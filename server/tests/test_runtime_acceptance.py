from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from support_faults import MutableClock, PausableAgent

from echo_server.agents.contracts import AgentInvocation, AgentRunResult
from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.domain.conversation import ConversationParticipant
from echo_server.domain.messages import SubmitMessageCommand
from echo_server.domain.state import CharacterAvailabilityStatus, CharacterState, WorldState
from echo_server.runtime.application_runtime import ApplicationRuntime
from echo_server.runtime.conversation_worker import ConversationWorker
from echo_server.store.database import Database

BASE_TIME = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


class FailOnceCharacterAgent(StubCharacterAgent):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("acceptance_provider_failure")
        return await super().run(invocation)


@pytest_asyncio.fixture
async def acceptance_runtime(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
        max_agent_attempts=1,
        retry_backoff_seconds=0,
        lease_seconds=30,
    )
    clock = MutableClock(BASE_TIME)
    runtime = ApplicationRuntime(
        Database(settings.database_path),
        StubCharacterAgent(),
        settings,
        clock=clock,
        worker_id="acceptance-worker",
    )
    await runtime.start()
    await seed_runtime_state(runtime, clock)
    yield runtime, clock
    if runtime.database.is_open:
        await runtime.stop()


async def seed_runtime_state(runtime: ApplicationRuntime, clock: MutableClock) -> None:
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


async def submit(runtime: ApplicationRuntime, text: str) -> UUID:
    receipt = await runtime.submit_message(
        SubmitMessageCommand(
            account_id=runtime.settings.account_id,
            conversation_id=runtime.settings.default_conversation_id,
            player_text=text,
            images=(),
            client_msg_id=uuid4(),
            local_timestamp=runtime.clock(),
        )
    )
    return receipt.message_id


async def claim_task(
    runtime: ApplicationRuntime,
    clock: MutableClock,
    *,
    seconds: int = 6,
    lease_seconds: float | None = None,
):
    clock.current = BASE_TIME + timedelta(seconds=seconds)
    task = await runtime.prepare_next_task()
    assert task is not None
    claimed = await runtime.runtime_tasks.claim_next(
        account_id=runtime.settings.account_id,
        conversation_id=runtime.settings.default_conversation_id,
        worker_id=runtime.worker_id,
        now_utc=clock.current,
        lease_seconds=runtime.settings.lease_seconds if lease_seconds is None else lease_seconds,
    )
    assert claimed is not None
    return claimed


async def conversation_messages(runtime: ApplicationRuntime) -> list[tuple[str, str]]:
    messages = await runtime.runtime_messages.list_conversation(
        runtime.settings.account_id,
        runtime.settings.default_conversation_id,
    )
    return [(message.sender.type.value, message.text) for message in messages]


@pytest.mark.asyncio
async def test_acceptance_freezes_task_input_while_next_batch_collects(acceptance_runtime):
    runtime, clock = acceptance_runtime
    agent = PausableAgent()
    runtime.agent = agent

    await submit(runtime, "first")
    task = await claim_task(runtime, clock)
    running = asyncio.create_task(runtime.execution.run_task(task.task_id))
    await asyncio.wait_for(agent.started.wait(), timeout=1)

    clock.current = BASE_TIME + timedelta(seconds=7)
    later_message_id = await submit(runtime, "later")
    later_row = await runtime.database.fetchone(
        "SELECT input_batch_id FROM messages WHERE message_id = ?",
        (str(later_message_id),),
    )
    assert later_row is not None
    later_batch = await runtime.input_batches.get(UUID(later_row["input_batch_id"]))
    assert later_batch is not None
    assert later_batch.status.value == "collecting"
    assert later_batch.task_id is None

    agent.release.set()
    assert await running

    clock.current = BASE_TIME + timedelta(seconds=13)
    worker = ConversationWorker(runtime)
    assert await worker.run_once()

    assert [message.text for message in agent.invocations[0].context.input_messages] == ["first"]
    assert [message.text for message in agent.invocations[1].context.input_messages] == ["later"]
    assert len({invocation.correlation.task_id for invocation in agent.invocations}) == 2
    assert await conversation_messages(runtime) == [
        ("player", "first"),
        ("player", "later"),
        ("character", "我在听。"),
        ("character", "我在听。"),
    ]


@pytest.mark.asyncio
async def test_acceptance_heartbeat_renews_a_long_running_task(acceptance_runtime):
    runtime, clock = acceptance_runtime
    runtime.settings = replace(
        runtime.settings,
        lease_seconds=0.2,
        lease_heartbeat_interval_seconds=0.01,
        lease_safety_margin_seconds=0,
    )
    agent = PausableAgent()
    runtime.agent = agent

    await submit(runtime, "heartbeat")
    task = await claim_task(runtime, clock, lease_seconds=0.2)
    running = asyncio.create_task(runtime.execution.run_task(task.task_id))
    await agent.wait_until_started()

    clock.current = BASE_TIME + timedelta(seconds=6, milliseconds=150)
    for _ in range(100):
        renewed = await runtime.runtime_tasks.get(task.task_id)
        if renewed is not None and renewed.lease_until_utc > task.lease_until_utc:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("lease heartbeat did not renew the task")

    agent.release_call()
    assert await running
    completed = await runtime.runtime_tasks.get(task.task_id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert not agent.cancelled.is_set()


@pytest.mark.asyncio
async def test_acceptance_failed_heartbeat_cancels_agent_and_requeues_task(
    acceptance_runtime, monkeypatch
):
    runtime, clock = acceptance_runtime
    runtime.settings = replace(
        runtime.settings,
        lease_seconds=0.2,
        lease_heartbeat_interval_seconds=0.01,
        lease_safety_margin_seconds=0,
        max_agent_attempts=2,
    )
    agent = PausableAgent()
    runtime.agent = agent

    await submit(runtime, "heartbeat failure")
    task = await claim_task(runtime, clock, lease_seconds=0.2)

    async def fail_renew(*args, **kwargs):
        raise RuntimeError("heartbeat database failure")

    monkeypatch.setattr(runtime.runtime_tasks, "renew_lease", fail_renew)
    running = asyncio.create_task(runtime.execution.run_task(task.task_id))
    await agent.wait_until_started()
    assert await running
    assert agent.cancelled.is_set()

    retrying = await runtime.runtime_tasks.get(task.task_id)
    assert retrying is not None
    assert retrying.status.value == "retry_wait"
    assert retrying.last_error_code == "lease_heartbeat_failed"
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM messages WHERE sender_type = 'character'"
        )
    )["count"] == 0

    monkeypatch.undo()
    runtime.agent = StubCharacterAgent({"xiaojin": "recovered after heartbeat"})
    clock.current = BASE_TIME + timedelta(seconds=6, milliseconds=100)
    worker = ConversationWorker(runtime)
    assert await worker.run_once()
    completed = await runtime.runtime_tasks.get(task.task_id)
    assert completed is not None
    assert completed.status.value == "completed"
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM messages WHERE sender_type = 'character'"
        )
    )["count"] == 1


@pytest.mark.asyncio
async def test_acceptance_fences_a_result_after_same_worker_reclaims_task(acceptance_runtime):
    runtime, clock = acceptance_runtime
    runtime.settings = replace(
        runtime.settings,
        lease_seconds=1,
        lease_heartbeat_interval_seconds=10,
        lease_safety_margin_seconds=0,
    )
    agent = PausableAgent()
    runtime.agent = agent

    await submit(runtime, "fenced result")
    first = await claim_task(runtime, clock, lease_seconds=1)
    running = asyncio.create_task(runtime.execution.run_task(first.task_id))
    await agent.wait_until_started()

    clock.current = BASE_TIME + timedelta(seconds=8)
    async with runtime.database.transaction(immediate=True) as connection:
        assert (
            await runtime.runtime_tasks.recover_expired(clock.current, connection=connection) == 1
        )
    reclaimed = await runtime.runtime_tasks.claim_next(
        worker_id=runtime.worker_id,
        now_utc=clock.current,
        lease_seconds=1,
        account_id=runtime.settings.account_id,
        conversation_id=runtime.settings.default_conversation_id,
    )
    assert reclaimed is not None
    assert reclaimed.attempt_count == first.attempt_count + 1
    assert reclaimed.lease_generation == first.lease_generation + 1

    agent.release_call()
    assert await running
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM messages WHERE sender_type = 'character'"
        )
    )["count"] == 0
    still_processing = await runtime.runtime_tasks.get(first.task_id)
    assert still_processing is not None
    assert still_processing.status.value == "processing"
    assert still_processing.lease_generation == reclaimed.lease_generation

    runtime.agent = StubCharacterAgent({"xiaojin": "accepted after reclaim"})
    clock.current = BASE_TIME + timedelta(seconds=8, milliseconds=100)
    assert await runtime.execution.run_task(reclaimed.task_id)
    completed = await runtime.runtime_tasks.get(reclaimed.task_id)
    assert completed is not None
    assert completed.status.value == "completed"
    message = await runtime.database.fetchone(
        "SELECT text FROM messages WHERE sender_type = 'character'"
    )
    assert message["text"] == "accepted after reclaim"


@pytest.mark.asyncio
async def test_acceptance_restart_recovers_task_and_continues_with_later_input(
    acceptance_runtime,
):
    runtime, clock = acceptance_runtime
    await submit(runtime, "before restart")
    task = await claim_task(runtime, clock, lease_seconds=1)
    database_path = runtime.settings.database_path
    await runtime.stop()

    clock.current = BASE_TIME + timedelta(seconds=8)
    restarted = ApplicationRuntime(
        Database(database_path),
        StubCharacterAgent({"xiaojin": "recovered"}),
        runtime.settings,
        clock=clock,
        worker_id="restarted-acceptance-worker",
    )
    await restarted.start()
    try:
        recovered = await restarted.runtime_tasks.get(task.task_id)
        assert recovered is not None
        assert recovered.status.value == "retry_wait"

        worker = ConversationWorker(restarted)
        assert await worker.run_once()
        completed = await restarted.runtime_tasks.get(task.task_id)
        assert completed is not None
        assert completed.status.value == "completed"

        clock.current = BASE_TIME + timedelta(seconds=14)
        await submit(restarted, "after restart")
        clock.current = BASE_TIME + timedelta(seconds=20)
        assert await worker.run_once()
        assert await conversation_messages(restarted) == [
            ("player", "before restart"),
            ("character", "recovered"),
            ("player", "after restart"),
            ("character", "recovered"),
        ]
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_acceptance_terminal_failure_does_not_block_a_later_batch(acceptance_runtime):
    runtime, clock = acceptance_runtime
    agent = FailOnceCharacterAgent()
    runtime.agent = agent
    first_message_id = await submit(runtime, "will fail")
    worker = ConversationWorker(runtime)

    clock.current = BASE_TIME + timedelta(seconds=6)
    assert await worker.run_once()
    first_row = await runtime.database.fetchone(
        "SELECT input_batch_id FROM messages WHERE message_id = ?",
        (str(first_message_id),),
    )
    assert first_row is not None
    first_batch = await runtime.input_batches.get(UUID(first_row["input_batch_id"]))
    assert first_batch is not None
    assert first_batch.status.value == "terminal_failed"
    failed_task = await runtime.runtime_tasks.get(first_batch.task_id)
    assert failed_task is not None
    assert failed_task.status.value == "failed"

    clock.current = BASE_TIME + timedelta(seconds=7)
    await submit(runtime, "continues")
    clock.current = BASE_TIME + timedelta(seconds=13)
    assert await worker.run_once()
    assert agent.calls == 2
    assert await conversation_messages(runtime) == [
        ("player", "will fail"),
        ("player", "continues"),
        ("character", "我在听。"),
    ]


@pytest.mark.asyncio
async def test_acceptance_worker_failure_is_observable(acceptance_runtime, monkeypatch):
    runtime, _ = acceptance_runtime
    worker = ConversationWorker(runtime)

    async def fail_run_once() -> bool:
        raise RuntimeError("acceptance_worker_failure")

    monkeypatch.setattr(worker, "run_once", fail_run_once)
    await worker.start()
    try:
        for _ in range(100):
            if worker.failure is not None:
                break
            await asyncio.sleep(0)
        assert isinstance(worker.failure, RuntimeError)
        assert str(worker.failure) == "acceptance_worker_failure"
    finally:
        await worker.stop()
