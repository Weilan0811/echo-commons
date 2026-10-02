import asyncio
from datetime import UTC, datetime

from test_memory_sealing import sealing
from test_message_perspective import build_system, send
from test_reflection_context import build_reflection

from echo_commons.execution.recovery import QueuePolicy
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.queue import ReflectionQueue


def prepare_queue(tmp_path, *, lease_seconds=30, max_attempts=3):
    system = build_system(tmp_path)
    send(system, "一起做一顿晚餐")
    context, coordinator = build_reflection(system)
    for character in ("first", "second"):
        segment = sealing(system).seal("community", character, "conversation")
        coordinator.start_segment("community", character, segment.segment_id)
    queue = ReflectionQueue(
        system.database,
        NodeRepository(),
        RunRepository(),
        QueuePolicy(lease_seconds, max_attempts, 0),
    )
    return system, context, coordinator, queue


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
            system.database, NodeRepository(), RunRepository(), queue.policy
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
        assert await queue.reschedule(
            lease, datetime.now(UTC), error_code="invalid_node_output", terminal=True
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
        assert not await queue.reschedule(
            lease, datetime.now(UTC), error_code="late_result", terminal=True
        )
        other = await queue.claim("second-worker", datetime.now(UTC))
        assert other is not None and other.task_id != lease.task_id

    asyncio.run(run())
