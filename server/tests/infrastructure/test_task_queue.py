import asyncio
from datetime import UTC, datetime

from support.queue import queue_system
from support.recovery import conversation_recovery

from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.execution.recovery import QueuePolicy, decision
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.conversations.tasks.queue import ConversationQueue


def test_concurrent_claims_have_distinct_owned_leases(tmp_path):
    system = queue_system(tmp_path, QueuePolicy())

    async def run():
        leases = await asyncio.gather(
            *(system.queue.claim(f"worker-{index}", datetime.now(UTC)) for index in range(5))
        )
        claimed = tuple(lease for lease in leases if lease is not None)
        assert len(claimed) == 1
        assert len({lease.task_id for lease in claimed}) == 1
        assert all(lease.attempt == 1 and lease.generation == 1 for lease in claimed)
        assert await system.queue.renew(claimed[0], datetime.now(UTC))

    asyncio.run(run())


def test_real_expired_lease_recovers_after_queue_reconstruction(tmp_path):
    system = queue_system(tmp_path, QueuePolicy(lease_seconds=0.03))

    async def run():
        first = await system.queue.claim("first-worker", datetime.now(UTC))
        second = await system.queue.claim("second-worker", datetime.now(UTC))
        assert second is None
        await asyncio.sleep(0.05)
        restarted = ConversationQueue(
            system.database,
            ConversationQueueRepository(),
            system.social,
            system.completion,
            QueuePolicy(retry_backoff_seconds=0),
            conversation_recovery(system, QueuePolicy(retry_backoff_seconds=0)),
        )
        assert await restarted.recover(datetime.now(UTC)) == 1
        reclaimed = await restarted.claim("restarted-worker", datetime.now(UTC))
        original = first
        assert reclaimed.attempt == 2 and reclaimed.generation == 2
        assert not await restarted.renew(original, datetime.now(UTC))
        assert not await restarted.apply_recovery(
            original,
            datetime.now(UTC),
            decision("late-result", FailureCategory.HARNESS, RecoveryAction.FAIL),
        )
        with system.database.read() as connection:
            row = system.tasks.get(connection, reclaimed.task_id)
            assert row["lease_owner"] == "restarted-worker"
            assert (
                row["snapshot_json"]
                == system.tasks.snapshot(connection, reclaimed.task_id).model_dump_json()
            )

    asyncio.run(run())


def test_terminal_failure_completes_participation_and_turn(tmp_path):
    system = queue_system(tmp_path, QueuePolicy(max_attempts=1))

    async def run():
        for owner in ("one", "two", "three"):
            lease = await system.queue.claim(owner, datetime.now(UTC))
            assert await system.queue.apply_recovery(
                lease,
                datetime.now(UTC),
                decision("provider_not_configured", FailureCategory.HARNESS, RecoveryAction.FAIL),
            )
            system.planner.plan()

    asyncio.run(run())
    with system.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM conversation_tasks WHERE status = 'failed'"
            ).fetchone()[0]
            == 3
        )
        turns = connection.execute("SELECT * FROM social_turns").fetchall()
        assert len(turns) == 3 and len({turn["chain_id"] for turn in turns}) == 1
        assert all(turn["status"] == "completed" for turn in turns)
        assert all(turn["completion_json"] == '{"failed":1}' for turn in turns)
        assert connection.execute("SELECT status FROM social_chains").fetchone()[0] == "completed"
