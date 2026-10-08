import asyncio
from datetime import UTC, datetime

from test_task_queue import queue_system

from echo_commons.execution.recovery import QueuePolicy
from echo_commons.modules.communities.domain import CommunityStatus
from echo_commons.shared.actors import ActorRef


def test_pause_releases_lease_and_resume_preserves_snapshot(tmp_path):
    system = queue_system(tmp_path, QueuePolicy())
    lease = asyncio.run(system.queue.claim("pause-worker", datetime.now(UTC)))
    with system.database.read() as connection:
        original = system.tasks.get(connection, lease.task_id)["snapshot_json"]
    system.communities.update("community", expected_version=1, status=CommunityStatus.PAUSED)
    with system.database.read() as connection:
        row = system.tasks.get(connection, lease.task_id)
        assert row["status"] == "suspended" and row["lease_owner"] is None
        assert row["snapshot_json"] == original
    assert not asyncio.run(system.queue.renew(lease, datetime.now(UTC)))
    system.communities.update("community", expected_version=2, status=CommunityStatus.ACTIVE)
    resumed = asyncio.run(system.queue.claim("resume-worker", datetime.now(UTC)))
    assert resumed is not None
    with system.database.read() as connection:
        assert system.tasks.get(connection, lease.task_id)["snapshot_json"] == original


def test_leaving_character_cancels_only_its_task_and_archive_completes_turn(tmp_path):
    system = queue_system(tmp_path, QueuePolicy())
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    system.planner.plan()
    with system.database.read() as connection:
        rows = {
            row["character_id"]: row["status"]
            for row in connection.execute("SELECT * FROM conversation_tasks")
        }
        assert rows == {"first": "cancelled", "second": "pending"}
        assert connection.execute("SELECT status FROM social_turns").fetchone()[0] == "running"
    system.conversations.archive("community", "conversation")
    with system.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM conversation_tasks WHERE status = 'cancelled'"
            ).fetchone()[0]
            == 2
        )
        assert connection.execute("SELECT status FROM social_turns").fetchone()[0] == "cancelled"
    assert asyncio.run(system.queue.claim("archived-worker", datetime.now(UTC))) is None
