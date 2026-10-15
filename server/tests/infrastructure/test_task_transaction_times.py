import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from support.application import settings_for
from support.reflection import prepare_queue, seed

from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.agents.contracts.run import AgentRunStatus
from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.execution.clock import utc_now
from echo_commons.execution.lease import with_heartbeat
from echo_commons.execution.recovery import decision


def waiting_write(database, queue, lease, operation):
    entered = Event()

    def submit():
        entered.set()
        return operation()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with database.transaction() as connection:
            pending = executor.submit(submit)
            assert entered.wait(5)
            assert not pending.done()
            node = queue.nodes.get(connection, lease.task_id)
            heartbeat_time = utc_now()
            queue.nodes.save(
                connection,
                node.renew_lease(
                    worker_id=lease.owner,
                    now_utc=heartbeat_time,
                    lease_until_utc=heartbeat_time + timedelta(seconds=30),
                    attempt_count=lease.attempt,
                    lease_generation=lease.generation,
                ),
            )
        result = pending.result(timeout=10)
    with database.read() as connection:
        saved = queue.nodes.get(connection, lease.task_id)
        assert saved.updated_at_utc >= heartbeat_time
    return result


@pytest.mark.parametrize("operation", ("renew", "recovery"))
def test_waiting_state_change_uses_transaction_time_after_heartbeat(tmp_path, operation):
    system, _, _, queue = prepare_queue(tmp_path)
    lease = asyncio.run(queue.claim("writer", utc_now()))
    scheduling_time = utc_now()

    def apply():
        if operation == "renew":
            return queue._renew(lease, scheduling_time)
        return queue._apply_recovery(
            lease,
            scheduling_time,
            decision("execution_cancelled", FailureCategory.HARNESS, RecoveryAction.FAIL),
        )

    assert waiting_write(system.database, queue, lease, apply)
    if operation == "recovery":
        assert not asyncio.run(queue.renew(lease, utc_now()))


def test_waiting_renewal_rechecks_expired_lease(tmp_path):
    system, _, _, queue = prepare_queue(tmp_path, lease_seconds=0.03)
    lease = asyncio.run(queue.claim("writer", utc_now()))
    entered = Event()

    def renew():
        entered.set()
        return queue._renew(lease, utc_now())

    with ThreadPoolExecutor(max_workers=1) as executor:
        with system.database.transaction():
            pending = executor.submit(renew)
            assert entered.wait(5)
            Event().wait(0.06)
        assert pending.result(timeout=10) is False


@pytest.mark.model
def test_real_model_result_commits_after_waiting_heartbeat_once(tmp_path):
    async def run():
        async with application_lifecycle(settings_for(tmp_path, workers=False)) as app:
            seed(app)
            queue = app.reflection_queue
            lease = await queue.claim("model-writer", utc_now())
            prepared = app.reflection_execution.prepare(lease.task_id, attempt=lease.attempt)
            result = await with_heartbeat(queue, lease, prepared.agent.run(prepared.invocation), 5)
            assert result.status is AgentRunStatus.COMPLETED
            scheduling_time = utc_now()
            artifact = waiting_write(
                app.database,
                queue,
                lease,
                lambda: app.reflection_commit.commit(
                    lease, prepared.invocation, result, scheduling_time
                ),
            )
            repeated = app.reflection_commit.commit(
                lease, prepared.invocation, result, scheduling_time
            )
            assert repeated.artifact_id == artifact.artifact_id
            assert not await queue.renew(lease, utc_now())
            with app.database.read() as connection:
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM reflection_artifacts WHERE node_task_id=?",
                        (lease.task_id,),
                    ).fetchone()[0]
                    == 1
                )
            app.communities.update("community", expected_version=1, status="paused")
            assert await queue.claim("paused-writer", utc_now()) is None

    asyncio.run(run())
