from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

from echo_commons.domain import (
    EvidenceRef,
    GraphReviewRecord,
    GraphReviewStatus,
    GraphSourceRef,
    OutputContractRef,
    ReflectionArtifact,
    ReflectionDependency,
    ReflectionGraphDefinition,
    ReflectionGraphRun,
    ReflectionNodeDefinition,
    ReflectionNodeTask,
    ReflectionSourceScope,
)
from echo_commons.domain.errors import DomainInvariantError
from echo_commons.store.database import Database
from echo_commons.store.migrations import migrate
from echo_commons.store.reflection_graph_repositories import (
    GraphReviewRepository,
    ReflectionArtifactRepository,
    ReflectionGraphRunRepository,
    ReflectionNodeTaskRepository,
)

BASE_TIME = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
NODE_CONTRACT = OutputContractRef(kind="reflection_node", version="v1")


@pytest_asyncio.fixture
async def database(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await migrate(database)
    yield database
    await database.close()


def build_definition() -> ReflectionGraphDefinition:
    return ReflectionGraphDefinition(
        graph_kind="test_graph",
        version="v1",
        nodes=(
            ReflectionNodeDefinition("root", "test_root", "snapshot.v1", NODE_CONTRACT),
            ReflectionNodeDefinition(
                "child",
                "test_child",
                "artifact.v1",
                NODE_CONTRACT,
                required=False,
            ),
        ),
        dependencies=(ReflectionDependency("root", "child"),),
    )


def build_run(*, source_ref: str = "segment:1") -> ReflectionGraphRun:
    return ReflectionGraphRun.create(
        graph_run_id=uuid4(),
        definition=build_definition(),
        account_id="account",
        character_id="xiaojin",
        context_snapshot_id="snapshot:1",
        snapshot_fingerprint="snapshot-v1",
        source_scope=ReflectionSourceScope(
            sources=(GraphSourceRef("segment", source_ref, "segment-v1"),)
        ),
        now_utc=BASE_TIME,
    )


def build_task(
    run: ReflectionGraphRun,
    *,
    node_key: str,
    activated: bool,
) -> ReflectionNodeTask:
    return ReflectionNodeTask.create(
        task_id=uuid4(),
        graph_run_id=run.graph_run_id,
        node_key=node_key,
        node_kind=f"test_{node_key}",
        dependency_keys=("root",) if node_key == "child" else (),
        node_input_fingerprint=f"input-{node_key}",
        output_contract=NODE_CONTRACT,
        now_utc=BASE_TIME,
        activated=activated,
    )


def build_artifact(task: ReflectionNodeTask, *, value: str) -> ReflectionArtifact:
    return ReflectionArtifact.create(
        artifact_id=uuid4(),
        graph_run_id=task.graph_run_id,
        node_task_id=task.task_id,
        attempt=task.attempt_count,
        node_input_fingerprint=task.node_input_fingerprint,
        output_contract=NODE_CONTRACT,
        payload={"kind": "test", "value": value},
        evidence_refs=(EvidenceRef("segment", "segment:1", "segment-v1"),),
        created_at_utc=BASE_TIME,
    )


@pytest.mark.asyncio
async def test_migration_exposes_only_the_four_graph_runtime_tables(database):
    tables = {
        row["name"]
        for row in await database.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'reflection%'"
        )
    }
    assert tables == {
        "reflection_graph_runs",
        "reflection_node_tasks",
        "reflection_artifacts",
        "reflection_graph_results",
    }
    columns = {
        row["name"]
        for row in await database.fetchall("PRAGMA table_info(reflection_graph_results)")
    }
    assert columns == {
        "result_id",
        "graph_run_id",
        "aggregate_fingerprint",
        "payload_json",
        "status",
        "decision_code",
        "created_at_utc",
        "decided_at_utc",
    }


@pytest.mark.asyncio
async def test_same_source_reuses_completed_run_and_changed_source_creates_new_run(database):
    repository = ReflectionGraphRunRepository(database)
    run = build_run()
    root = build_task(run, node_key="root", activated=True)

    async with database.transaction(immediate=True) as connection:
        stored, _ = await repository.ensure_with_root_tasks(
            run, (root,), now_utc=BASE_TIME, connection=connection
        )
        completed = stored.complete(
            now_utc=BASE_TIME + timedelta(seconds=1), completed_node_keys=("root",)
        )
        stored = await repository.save(completed, connection=connection)

    async with database.transaction(immediate=True) as connection:
        repeated, roots = await repository.ensure_with_root_tasks(
            run,
            (root,),
            now_utc=BASE_TIME + timedelta(seconds=2),
            connection=connection,
        )
    assert repeated.graph_run_id == stored.graph_run_id
    assert repeated.status.value == "completed"
    assert roots == (root,)

    changed = build_run(source_ref="segment:2")
    async with database.transaction(immediate=True) as connection:
        created, _ = await repository.ensure_with_root_tasks(
            changed,
            (build_task(changed, node_key="root", activated=True),),
            now_utc=BASE_TIME,
            connection=connection,
        )
    assert created.graph_run_id != stored.graph_run_id


@pytest.mark.asyncio
async def test_failed_source_reactivates_the_same_run_and_node(database):
    graph_repository = ReflectionGraphRunRepository(database)
    node_repository = ReflectionNodeTaskRepository(database)
    run = build_run()
    root = build_task(run, node_key="root", activated=True)

    async with database.transaction(immediate=True) as connection:
        started, _ = await graph_repository.ensure_with_root_tasks(
            run, (root,), now_utc=BASE_TIME, connection=connection
        )
    claimed = await node_repository.claim_next(
        graph_run_id=started.graph_run_id,
        worker_id="worker-1",
        now_utc=BASE_TIME,
        lease_seconds=5,
    )
    assert claimed is not None
    async with database.transaction(immediate=True) as connection:
        failed_task = await node_repository.retry_or_fail(
            claimed.task_id,
            worker_id="worker-1",
            now_utc=BASE_TIME + timedelta(seconds=1),
            available_at_utc=BASE_TIME + timedelta(seconds=1),
            error_code="model_failed",
            max_attempts=1,
            attempt_count=claimed.attempt_count,
            lease_generation=claimed.lease_generation,
            connection=connection,
        )
    assert failed_task.status.value == "failed"
    failed_run = started.fail(now_utc=BASE_TIME + timedelta(seconds=2), error_code="node_failed")
    async with database.transaction(immediate=True) as connection:
        await graph_repository.save(failed_run, connection=connection)

    async with database.transaction(immediate=True) as connection:
        reactivated, _ = await graph_repository.ensure_with_root_tasks(
            run,
            (root,),
            now_utc=BASE_TIME + timedelta(seconds=3),
            connection=connection,
        )
    assert reactivated.graph_run_id == started.graph_run_id
    assert reactivated.status.value == "running"
    assert reactivated.execution_generation == 2
    current = await node_repository.get_for_graph_node(reactivated.graph_run_id, "root")
    assert current is not None
    assert current.status.value == "pending"


@pytest.mark.asyncio
async def test_node_artifact_and_graph_review_repositories_share_graph_identity(database):
    graph_repository = ReflectionGraphRunRepository(database)
    node_repository = ReflectionNodeTaskRepository(database)
    artifact_repository = ReflectionArtifactRepository(database)
    review_repository = GraphReviewRepository(database)
    run = build_run()
    root = build_task(run, node_key="root", activated=True)

    async with database.transaction(immediate=True) as connection:
        started, _ = await graph_repository.ensure_with_root_tasks(
            run, (root,), now_utc=BASE_TIME, connection=connection
        )
    claim = await node_repository.claim_next(
        graph_run_id=started.graph_run_id,
        worker_id="worker-1",
        now_utc=BASE_TIME,
        lease_seconds=5,
    )
    assert claim is not None
    artifact = build_artifact(claim, value="summary")
    async with database.transaction(immediate=True) as connection:
        completed = await node_repository.complete_with_artifact(
            claim.task_id,
            artifact,
            worker_id="worker-1",
            now_utc=BASE_TIME + timedelta(seconds=1),
            attempt_count=claim.attempt_count,
            lease_generation=claim.lease_generation,
            connection=connection,
        )
    assert completed.artifact == artifact
    assert await artifact_repository.get_for_task_attempt(claim.task_id, 1) == artifact

    review = GraphReviewRecord(
        result_id=uuid4(),
        graph_run_id=started.graph_run_id,
        aggregate_fingerprint="aggregate-v1",
        payload_json='{"outcome":"no_op"}',
        created_at_utc=BASE_TIME + timedelta(seconds=2),
    )
    async with database.transaction(immediate=True) as connection:
        stored = await review_repository.ensure(review, connection=connection)
    assert stored == review
    decided = review.decide(
        status=GraphReviewStatus.SKIPPED,
        decided_at_utc=BASE_TIME + timedelta(seconds=3),
        decision_code="no_op",
    )
    async with database.transaction(immediate=True) as connection:
        saved = await review_repository.save_decision(decided, connection=connection)
    assert saved == decided

    with pytest.raises(DomainInvariantError, match="different Artifact"):
        async with database.transaction(immediate=True) as connection:
            await artifact_repository.ensure(
                build_artifact(claim, value="changed"), connection=connection
            )
