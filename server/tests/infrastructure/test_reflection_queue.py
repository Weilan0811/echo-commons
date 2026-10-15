import asyncio
from datetime import UTC, datetime

from support.messages import send
from support.recovery import reflection_recovery
from support.reflection import prepare_queue

from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.execution.recovery import decision
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.queue import ReflectionQueue


def test_parallel_claims_assign_distinct_owned_nodes(tmp_path):
    system, _, _, queue = prepare_queue(tmp_path)

    async def run():
        leases = await asyncio.gather(
            *(queue.claim(f"worker-{index}", datetime.now(UTC)) for index in range(5))
        )
        claimed = tuple(lease for lease in leases if lease is not None)
        assert len(claimed) == 2
        assert len({lease.task_id for lease in claimed}) == 2
        for lease in claimed:
            assert await queue.renew(lease, datetime.now(UTC))
            with system.database.read() as connection:
                assert queue.owned(connection, lease, datetime.now(UTC))
                node = NodeRepository().get(connection, lease.task_id)
                assert node.node_key == "segment_summary_plan"
                assert queue.run_for(connection, node).status == "running"

    asyncio.run(run())


def test_expired_node_lease_recovers_original_snapshot(tmp_path):
    system, _, _, queue = prepare_queue(tmp_path, lease_seconds=0.03)

    async def run():
        lease = await queue.claim("interrupted-worker", datetime.now(UTC))
        with system.database.read() as connection:
            node = NodeRepository().get(connection, lease.task_id)
            graph = queue.run_for(connection, node)
            snapshot = RunRepository().snapshot(
                connection,
                graph.community_id,
                graph.character_id,
                str(graph.graph_run_id),
            )
        await asyncio.sleep(0.05)
        restarted = ReflectionQueue(
            system.database,
            NodeRepository(),
            RunRepository(),
            queue.policy,
            reflection_recovery(system.database, queue.policy),
        )
        assert await restarted.recover(datetime.now(UTC)) == 1
        claims = tuple(
            [await restarted.claim("restarted-worker", datetime.now(UTC)) for _ in range(2)]
        )
        recovered = next(claim for claim in claims if claim.task_id == lease.task_id)
        assert recovered.task_id == lease.task_id
        assert (recovered.attempt, recovered.generation) == (2, 2)
        assert not await restarted.renew(lease, datetime.now(UTC))
        with system.database.read() as connection:
            fresh = NodeRepository().get(connection, recovered.task_id)
            assert fresh.node_input_fingerprint == node.node_input_fingerprint
            assert (
                RunRepository().snapshot(
                    connection,
                    graph.community_id,
                    graph.character_id,
                    str(graph.graph_run_id),
                )
                == snapshot
            )

    asyncio.run(run())


def test_terminal_required_failure_ends_only_its_graph(tmp_path):
    system, _, _, queue = prepare_queue(tmp_path)

    async def run():
        lease = await queue.claim("first-worker", datetime.now(UTC))
        assert await queue.apply_recovery(
            lease,
            datetime.now(UTC),
            decision("invalid_node_output", FailureCategory.HARNESS, RecoveryAction.FAIL),
        )
        with system.database.read() as connection:
            node = NodeRepository().get(connection, lease.task_id)
            graph = queue.run_for(connection, node)
            assert node.status == "failed" and graph.status == "failed"
            remaining = NodeRepository().for_graph(connection, str(graph.graph_run_id))
            assert {item.status for item in remaining} == {"failed", "skipped"}
            assert (
                connection.execute("SELECT COUNT(*) FROM reflection_artifacts").fetchone()[0] == 0
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM reflection_graph_runs WHERE status = 'pending'"
                ).fetchone()[0]
                == 1
            )
        assert not await queue.apply_recovery(
            lease,
            datetime.now(UTC),
            decision("late_result", FailureCategory.HARNESS, RecoveryAction.FAIL),
        )
        other = await queue.claim("second-worker", datetime.now(UTC))
        assert other is not None and other.task_id != lease.task_id

    asyncio.run(run())


def test_explicit_reschedule_restarts_failed_graph_with_frozen_input(tmp_path):
    system, _, coordinator, queue = prepare_queue(tmp_path)

    async def run():
        lease = await queue.claim("interrupted-worker", datetime.now(UTC))
        with system.database.read() as connection:
            node = queue.nodes.get(connection, lease.task_id)
            graph = queue.run_for(connection, node)
            snapshot = queue.runs.snapshot(
                connection, graph.community_id, graph.character_id, str(graph.graph_run_id)
            )
        assert await queue.apply_recovery(
            lease,
            datetime.now(UTC),
            decision("execution_cancelled", FailureCategory.HARNESS, RecoveryAction.FAIL),
        )
        send(system, "重新启动之后才出现的消息")
        resumed = coordinator.start_segment("community", graph.character_id, snapshot.source_id)
        assert resumed.graph_run_id == graph.graph_run_id
        assert resumed.status == "pending"
        with system.database.read() as connection:
            assert (
                queue.runs.snapshot(
                    connection, graph.community_id, graph.character_id, str(graph.graph_run_id)
                )
                == snapshot
            )
            nodes = queue.nodes.for_graph(connection, str(graph.graph_run_id))
            assert all(item.status == "pending" for item in nodes)
            assert {item.node_key for item in nodes if item.activated} == {
                "segment_summary_plan",
                "segment_aggregate",
            }
        claims = [await queue.claim("restarted-worker", datetime.now(UTC)) for _ in range(2)]
        restarted = next(item for item in claims if item.task_id == lease.task_id)
        assert restarted.attempt == lease.attempt + 1
        assert restarted.generation == lease.generation + 1
        assert not await queue.renew(lease, datetime.now(UTC))
        assert not await queue.apply_recovery(
            lease,
            datetime.now(UTC),
            decision("late_result", FailureCategory.HARNESS, RecoveryAction.FAIL),
        )
        with system.database.read() as connection:
            assert (
                queue.run_for(connection, queue.nodes.get(connection, lease.task_id)).status
                == "running"
            )
            assert (
                queue.run_for(
                    connection, queue.nodes.get(connection, lease.task_id)
                ).execution_generation
                == 2
            )

    asyncio.run(run())
