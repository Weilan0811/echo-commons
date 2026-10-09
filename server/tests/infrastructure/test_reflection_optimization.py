import asyncio
import shutil
import socket
from dataclasses import replace
from datetime import UTC, datetime
from importlib.resources import files

import httpx
import pytest
from historical_database import copy_to_historical_schema
from openai import APIStatusError
from test_application_lifecycle import settings_for
from test_final_acceptance import create_conversation
from test_memory_sealing import sealing
from test_message_perspective import build_system, send
from test_reflection_context import build_reflection
from test_reflection_queue import prepare_queue

from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.execution.contracts import Disposition
from echo_commons.execution.recovery import decision
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.infrastructure.models.errors import classify_provider_error
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.modules.characters.domain.state import InitialState
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind, ReflectionNodeKind
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.projection import project_node_input


def test_initial_state_defaults_overrides_and_historical_migration(tmp_path):
    system = build_system(tmp_path)
    with system.database.read() as connection:
        values = dict(
            connection.execute(
                "SELECT state_kind,value FROM character_state_entries WHERE character_id='first'"
            )
        )
    assert values == InitialState().model_dump()
    catalog = load_blueprint_catalog()
    blueprint = catalog.blueprint("xiaojin")
    system.characters.catalog = replace(
        catalog,
        blueprints={"xiaojin": replace(blueprint, initial_state=InitialState(physical="正在养伤"))},
    )
    system.characters.create("community", "xiaojin", character_id="injured")
    with system.database.transaction() as connection:
        assert (
            connection.execute(
                "SELECT value FROM character_state_entries "
                "WHERE character_id='injured' AND state_kind='physical'"
            ).fetchone()[0]
            == "正在养伤"
        )
        connection.execute("UPDATE character_state_entries SET value='' WHERE character_id='first'")
        connection.execute(
            "INSERT INTO character_state_entries SELECT 'later-state', community_id, "
            "character_id,state_kind,'有些疲惫','reflection','observed',2,recorded_at_utc,NULL "
            "FROM character_state_entries WHERE character_id='first' AND state_kind='physical'"
        )
    sql = tmp_path / "old-sql"
    sql.mkdir()
    for source in files("echo_commons.infrastructure.database.sql").iterdir():
        if source.name.endswith(".sql") and source.name < "0009":
            shutil.copyfile(str(source), sql / source.name)
    old = copy_to_historical_schema(system.database, sql, tmp_path / "old.sqlite3")
    assert initialize(old) == initialize(old) == 11
    with old.read() as connection:
        values = dict(
            connection.execute(
                "SELECT state_kind,value FROM character_state_entries "
                "WHERE character_id='first' AND source_kind='initialization'"
            )
        )
        assert values == {"mood": "平和", "activity": "空闲", "physical": ""}
        assert (
            connection.execute(
                "SELECT value FROM character_state_entries WHERE entry_id='later-state'"
            ).fetchone()[0]
            == "有些疲惫"
        )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_compression_projection_excludes_persona_and_background_memory(tmp_path):
    system = build_system(tmp_path)
    send(system, "记住这次约定")
    segment = sealing(system).seal("community", "first", "conversation")
    _, coordinator = build_reflection(system)
    with system.database.transaction() as connection:
        SegmentRepository().ingest(
            connection,
            "community",
            "first",
            segment.segment_id,
            "我和对方约定记住这次谈话。",
            datetime.now(UTC),
        )
    batches = SummaryBatches(
        system.database,
        InstanceRepository(),
        ConversationRepository(),
        system.world,
        MemoryProvenanceRepository(),
        max_materials=256,
        max_chars=20000,
    )
    with system.database.transaction() as connection:
        batch = batches.freeze_in(
            connection,
            "community",
            "first",
            "conversation",
            SummaryConsumer.CONTINUITY,
            through_sequence=1,
            limit=16,
        )
    run = coordinator.start_summary(
        "community",
        "first",
        batch.batch_id,
        ReflectionGraphKind.CONTINUITY_COMPRESS,
    )
    with system.database.read() as connection:
        snapshot = coordinator.runs.snapshot(
            connection, "community", "first", str(run.graph_run_id)
        )
    node = prepare_node_input(
        snapshot,
        graph_run_id=str(run.graph_run_id),
        node_task_id="projection",
        node_key="continuity_compress",
        node_kind=ReflectionNodeKind.CONTINUITY_COMPRESS,
    )
    projected = project_node_input(node)
    assert projected.memory == projected.state == projected.relationships == ""
    assert len(projected.identity_sections) == 1
    assert snapshot.self.name in projected.identity_sections[0][1]
    assert snapshot.self.profile not in projected.identity_sections[0][1]
    assert projected.materials == snapshot.materials
    assert len(projected.materials) == 1


def test_provider_retry_budget_delays_and_manual_restart(tmp_path):
    system, _, coordinator, queue = prepare_queue(tmp_path)
    error = APIStatusError(
        "private provider response",
        body=None,
        response=httpx.Response(
            503,
            headers={"retry-after": "45"},
            request=httpx.Request("POST", "https://provider.invalid"),
        ),
    )
    recovery = queue.recovery.classify(classify_provider_error(error))
    assert recovery.failure.status_code == 503
    assert recovery.failure.exception_type == "APIStatusError"

    async def run():
        now = datetime.now(UTC)
        lease = await queue.claim("retry", now)
        await queue.claim("other-character", now)
        first_id = lease.task_id
        review = decision("repairable_output", FailureCategory.REVIEW, RecoveryAction.RETRY_TASK)
        for attempt in range(1, 4):
            now = datetime.now(UTC)
            applied = await queue.apply_recovery(lease, now, review)
            assert applied.retry_exhausted == (attempt == 3)
            if attempt < 3:
                lease = await queue.claim("review-retry", now)
        with system.database.read() as connection:
            node = queue.nodes.get(connection, lease.task_id)
            graph = queue.run_for(connection, node)
        coordinator.restart("community", graph.character_id, str(graph.graph_run_id))
        now = datetime.now(UTC)
        lease = await queue.claim("manual-retry", now)
        assert lease.task_id == first_id and lease.attempt == 4
        for index, minimum in enumerate((45, 120, 600), start=1):
            applied = await queue.apply_recovery(lease, now, recovery)
            assert not applied.retry_exhausted
            assert minimum <= applied.effective_wait_seconds <= max(45, minimum * 1.1)
            assert await queue.claim("early", now) is None
            now = applied.next_attempt_at_utc
            lease = await queue.claim("retry", now)
            assert lease.task_id == first_id and lease.attempt == index + 4
        applied = await queue.apply_recovery(lease, now, recovery)
        assert applied.retry_exhausted and applied.task_state == "failed"
        with system.database.read() as connection:
            node = queue.nodes.get(connection, lease.task_id)
            assert node.attempt_base_count == 3
            payload = connection.execute(
                "SELECT payload_json FROM task_execution_events WHERE task_id=? "
                "AND event_kind='recovery_applied' ORDER BY event_id DESC LIMIT 1",
                (first_id,),
            ).fetchone()[0]
            assert '"status_code":503' in payload
            assert "private provider response" not in payload

    asyncio.run(run())


def test_input_too_large_is_not_quota_or_retryable(tmp_path):
    _, _, _, queue = prepare_queue(tmp_path)
    error = APIStatusError(
        "request too large",
        body=None,
        response=httpx.Response(
            413,
            request=httpx.Request("POST", "https://provider.invalid"),
        ),
    )
    recovery = queue.recovery.classify(classify_provider_error(error))
    assert recovery.failure.code == "input_too_large"
    assert recovery.failure.category is FailureCategory.CONFIGURATION
    assert recovery.action is RecoveryAction.FAIL


@pytest.mark.model
def test_reflection_network_failure_has_one_provider_attempt_and_saved_diagnostics(tmp_path):
    async def run():
        async with application_lifecycle(settings_for(tmp_path, workers=False)) as app:
            create_conversation(app)
            segment = app.memory_sealing.seal("community", "first", "conversation")
            app.reflection.start_segment("community", "first", segment.segment_id)
            handler = app.supervisor.workers["reflection-0"].dispatcher.registry.resolve(
                "reflection"
            )
            lease = await app.reflection_queue.claim("network-check", datetime.now(UTC))
            prepared = handler.execution.prepare(lease.task_id, attempt=lease.attempt)
            # 真实绑定但不监听端口，操作系统会拒绝连接。
            with socket.socket() as endpoint:
                endpoint.bind(("127.0.0.1", 0))
                port = endpoint.getsockname()[1]
                entries = {
                    key: replace(
                        value,
                        base_url=f"http://127.0.0.1:{port}",
                        request_timeout_seconds=2,
                        max_retries=1,
                    )
                    for key, value in app.models.entries.items()
                }
                gateway = OpenAICompatibleGateway(replace(app.models, entries=entries))
                prepared.agent.backend._loop.gateway = gateway
                try:
                    outcome = await handler.execute(lease)
                    assert outcome.disposition is Disposition.RECOVERY_REQUIRED
                    assert outcome.observation.provider_attempt_count == 1
                    assert outcome.recovery.failure.exception_type in {
                        "APIConnectionError",
                        "TimeoutError",
                        "APITimeoutError",
                    }
                    applied = await app.reflection_queue.apply_recovery(
                        lease,
                        datetime.now(UTC),
                        outcome.recovery,
                        outcome.observation,
                    )
                    assert 30 <= applied.effective_wait_seconds <= 33
                    with app.database.read() as connection:
                        payload = connection.execute(
                            "SELECT payload_json FROM task_execution_events WHERE task_id=? "
                            "AND event_kind='recovery_applied' ORDER BY event_id DESC LIMIT 1",
                            (lease.task_id,),
                        ).fetchone()[0]
                        assert outcome.recovery.failure.exception_type in payload
                finally:
                    await gateway.close()

    asyncio.run(run())
