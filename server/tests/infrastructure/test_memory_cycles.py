from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.authoring import confirm, create_draft
from support.http import create_group

from echo_commons.app.main import create_app
from echo_commons.modules.memory.domain.cycles import PendingMaterials
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.reflection.scheduling import MemoryScheduling
from echo_commons.shared.errors import ConflictError


def send(client, identifier, text="今天一起修理蓝风铃。"):
    response = client.post(
        "/api/conversations/conversation/messages",
        json=dict(player_id="alice", client_message_id=identifier, text=text),
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_simple_preparation_finishes_before_chat_and_full_waits_for_organization(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, _ = create_draft(client, story="小时候在青石镇修理旧钟。")
        blueprint, _ = confirm(client, draft)
        for mode in ("simple", "full"):
            response = client.post(
                "/api/communities/community/characters",
                json=dict(
                    player_id="alice",
                    blueprint_id=blueprint["blueprint_id"],
                    character_id=mode,
                    memory_mode=mode,
                ),
            )
            assert response.json()["memory_status"] == "preparing"
        application = client.app.state.application
        preparation = application.supervisor.workers["memory-preparation"]
        assert preparation.prepare_materials()
        assert preparation.prepare_materials()
        assert not preparation.prepare_materials()
        with application.database.read() as connection:
            simple = application.characters.instances.get(connection, "community", "simple")
            full = application.characters.instances.get(connection, "community", "full")
            assert simple.memory_status == "ready" and simple.memory_phase == "completed"
            assert full.memory_status == "preparing" and full.memory_phase == "organize"
            assert (
                connection.execute("SELECT COUNT(*) FROM memory_author_chunks").fetchone()[0] == 2
            )


def test_common_cycle_trigger_uses_oldest_material_and_either_threshold():
    now = datetime.now(UTC)
    small = PendingMaterials(200, 2, now - timedelta(seconds=31))
    assert small.due(now, target_chars=12000, wait_seconds=30)
    assert not small.due(now, target_chars=12000, wait_seconds=32)
    assert small.due(now, target_chars=200, wait_seconds=7200)
    assert not PendingMaterials(0, 0, now).due(now, target_chars=1, wait_seconds=1)
    assert PendingMaterials(1, 1, now, True).due(now, target_chars=12000, wait_seconds=7200)


def test_segment_trigger_freezes_only_one_batch_and_restart_keeps_pending_age(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"reflection_max_messages_per_segment": 1}
    )
    with TestClient(create_app(settings)) as client:
        create_group(client, memory_mode="simple")
        first = send(client, "first")
        second = send(client, "second")
        application = client.app.state.application
        worker = application.supervisor.workers["memory-cycles"]
        assert worker.scan(datetime.now(UTC)) == 2
        with application.database.read() as connection:
            segments = connection.execute("SELECT * FROM memory_segment_scenes").fetchall()
            assert len(segments) == 2 and all(
                row["first_sequence"] == first["sequence"]
                and row["last_sequence"] == first["sequence"]
                for row in segments
            )
            messages, _, _, _ = application.memory_sealing.pending(
                connection, "community", "first", datetime.now(UTC)
            )
            assert len(messages) == 1 and messages[0].message_id == second["message_id"]
            oldest = messages[0].created_at_utc
        restarted = MemoryScheduling(
            application.memory_sealing, application.reflection_workflow, settings.memory.cycles
        )
        assert restarted.scan(datetime.now(UTC) + timedelta(hours=4)) == 0
        with application.database.read() as connection:
            messages, _, _, _ = application.memory_sealing.pending(
                connection, "community", "first", datetime.now(UTC)
            )
            assert messages[0].created_at_utc == oldest
            assert (
                connection.execute("SELECT COUNT(*) FROM reflection_graph_runs").fetchone()[0] == 2
            )


def test_time_trigger_ignores_continued_input_and_simple_blocks_long_term_batches(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode="simple")
        send(client, "old")
        application = client.app.state.application
        worker = application.supervisor.workers["memory-cycles"]
        assert worker.scan(datetime.now(UTC)) == 0
        send(client, "new")
        assert worker.scan(datetime.now(UTC) + timedelta(seconds=1801)) == 2
        with application.database.read() as connection:
            segment_id = connection.execute(
                "SELECT segment_id FROM memory_segments WHERE character_id='first'"
            ).fetchone()[0]
        with application.database.transaction() as connection:
            MemoryIngestion(SegmentRepository(), CoverageRepository()).ingest(
                connection, "community", "first", segment_id, "约定修理蓝风铃。", datetime.now(UTC)
            )
        with pytest.raises(ConflictError):
            application.reflection_workflow.schedule_summaries(
                "community",
                "first",
                SummaryConsumer.ORGANIZATION,
            )
        assert worker.scan(datetime.now(UTC) + timedelta(hours=3)) == 1
        assert worker.scan(datetime.now(UTC) + timedelta(hours=6)) == 0
