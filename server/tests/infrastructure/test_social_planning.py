from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from historical_messages import historical_message
from test_message_perspective import build_system

from echo_commons.modules.characters.domain.instance import AvailabilityStatus
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.services.state import CharacterStateService
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog
from echo_commons.modules.communities.domain import CommunityStatus
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.tasks.context import ContextPolicy, ConversationContext
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.participation import Candidate, choose
from echo_commons.modules.social.planner import TurnPlanner
from echo_commons.modules.social.repository import SocialRepository
from echo_commons.shared.actors import ActorRef


def build_planning_system(tmp_path, *, sql_directory=None):
    base = build_system(tmp_path, sql_directory=sql_directory)
    base.intake.quiet_seconds = 0
    base.characters.create("community", "xiaojin", character_id="third", memory_mode="full")
    base.conversations.join("community", "conversation", ActorRef("character", "third"))
    social, tasks = SocialRepository(), ConversationTaskRepository()
    context = ConversationContext(
        ContextPolicy(20, 6000, 32, frozenset({"memory_search"}), 4),
        load_blueprint_catalog(),
        CommunityRepository(),
        base.conversations.conversations,
        InstanceRepository(),
        StateRepository(),
        RelationshipRepository(),
        MemoryEntryRepository(),
        MemoryProvenanceRepository(),
        base.world,
        base.retrieval,
        CapabilityResolver(frozenset({"memory_search"})),
    )
    base.social, base.tasks, base.completion = social, tasks, TurnCompletion(social)
    base.planner = TurnPlanner(
        base.database,
        CommunityRepository(),
        base.conversations.conversations,
        InstanceRepository(),
        base.messages,
        base.batches,
        social,
        tasks,
        base.perspective,
        context,
        base.completion,
    )
    return base


@pytest.fixture
def system(tmp_path):
    return build_planning_system(tmp_path)


def send(system, text="一起讨论", *, mentions=()):
    return system.intake.send(
        "community",
        "conversation",
        PlayerMessage("alice", text, text, mentions=mentions),
    )


def test_participation_priority_is_deterministic():
    now = datetime.now(UTC)
    candidates = (
        Candidate("old", False, now),
        Candidate("new", False, None),
        Candidate("mentioned", True, now),
        Candidate("absent", True, None, "member_left"),
    )
    assert choose(candidates, 2) == ("mentioned", "new")


def test_same_audience_player_batches_combine_exact_sources(system):
    first = send(system, "甲的输入")
    second = system.intake.send(
        "community", "conversation", PlayerMessage("bob", "bob-input", "乙的输入")
    )
    assert len(system.planner.plan()) == 1
    with system.database.read() as connection:
        rows = connection.execute("SELECT task_id FROM conversation_tasks").fetchall()
        assert all(
            {
                message.message_id
                for message in system.tasks.snapshot(connection, row[0]).perspective.inputs
            }
            == {first.message_id, second.message_id}
            for row in rows
        )
        assert connection.execute("SELECT COUNT(*) FROM social_turn_batches").fetchone()[0] == 2


def test_one_turn_prepares_independent_snapshots_and_limits_responders(system):
    source = send(system, mentions=(ActorRef("character", "third"),))
    turns = system.planner.plan()
    assert len(turns) == 1
    with system.database.read() as connection:
        decisions = system.social.decisions(connection, turns[0])
        assert {item.character_id for item in decisions if item.status == "selected"} == {
            "third",
            "first",
        }
        assert (
            next(item for item in decisions if item.character_id == "second").reason_code
            == "responder_limit"
        )
        rows = connection.execute("SELECT * FROM conversation_tasks").fetchall()
        snapshots = [system.tasks.snapshot(connection, row["task_id"]) for row in rows]
        assert len(snapshots) == 2 and len({snapshot.snapshot_id for snapshot in snapshots}) == 2
        assert {snapshot.scope.character_id for snapshot in snapshots} == {"third", "first"}
        assert all(
            snapshot.scope.observation_upper_sequence == source.sequence for snapshot in snapshots
        )
        assert all(
            snapshot.perspective.inputs[0].message_id == source.message_id for snapshot in snapshots
        )
        assert not set(memory.memory_id for memory in snapshots[0].memory.resident) & set(
            memory.memory_id for memory in snapshots[1].memory.resident
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert system.planner.plan() == ()


def test_parallel_planners_cannot_duplicate_turns_tasks_or_snapshots(system):
    send(system)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: system.planner.plan(), range(3)))
    assert sum(len(result) for result in results) == 1
    with system.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM social_turns").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 2


def test_snapshot_is_unchanged_after_new_state_and_message(system):
    send(system)
    system.planner.plan()
    with system.database.read() as connection:
        task_id = connection.execute(
            "SELECT task_id FROM conversation_tasks WHERE character_id = 'first'"
        ).fetchone()[0]
        before = system.tasks.snapshot(connection, task_id)
    states = CharacterStateService(system.database, InstanceRepository(), StateRepository())
    states.record(
        "community", "first", StateKind.MOOD, "新情绪", "reviewed_result", "new", expected_version=1
    )
    send(system, "后来的输入")
    assert system.planner.plan() == ()
    with system.database.read() as connection:
        assert system.tasks.snapshot(connection, task_id) == before
        assert before.self.mood == ""
        assert all(
            message.text != "后来的输入"
            for message in before.perspective.inputs + before.perspective.history
        )
        assert len(system.batches.awaiting(connection)) == 1


def test_private_sources_only_select_original_recipient_role(system):
    historical_message(system, recipients=(ActorRef("character", "second"),))
    turn_id = system.planner.plan()[0]
    with system.database.read() as connection:
        assert {
            decision.character_id
            for decision in system.social.decisions(connection, turn_id)
            if decision.status == "selected"
        } == {"second"}
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 1


def test_pause_retains_sources_until_resume(system):
    send(system)
    system.communities.update("community", expected_version=1, status=CommunityStatus.PAUSED)
    assert system.planner.plan() == ()
    system.communities.update("community", expected_version=2, status=CommunityStatus.ACTIVE)
    assert len(system.planner.plan()) == 1


def test_everyone_unavailable_completes_without_tasks(system):
    states = CharacterStateService(system.database, InstanceRepository(), StateRepository())
    for character in ("first", "second", "third"):
        states.set_availability("community", character, AvailabilityStatus.BUSY, expected_version=0)
    send(system)
    turn_id = system.planner.plan()[0]
    with system.database.read() as connection:
        assert system.social.get(connection, "community", turn_id).status == "completed"
        assert all(
            item.reason_code == "unavailable"
            for item in system.social.decisions(connection, turn_id)
        )
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 0


def test_one_failure_keeps_other_participant_running(system):
    send(system)
    turn_id = system.planner.plan()[0]
    with system.database.transaction() as connection:
        connection.execute(
            "UPDATE participation_decisions SET status = 'failed', outcome = 'failed' "
            "WHERE social_turn_id = ? AND character_id = 'first'",
            (turn_id,),
        )
        assert not system.completion.update(connection, turn_id, datetime.now(UTC))
        connection.execute(
            "UPDATE participation_decisions SET status = 'completed', outcome = 'silent' "
            "WHERE social_turn_id = ? AND character_id = 'second'",
            (turn_id,),
        )
        assert system.completion.update(connection, turn_id, datetime.now(UTC))
        assert system.social.get(connection, "community", turn_id).status == "completed"


def test_rejoining_cannot_use_previous_audience_membership(system):
    historical_message(system, recipients=(ActorRef("character", "first"),))
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    system.conversations.join("community", "conversation", ActorRef("character", "first"))
    turn_id = system.planner.plan()[0]
    with system.database.read() as connection:
        assert system.social.get(connection, "community", turn_id).status == "completed"
        first = next(
            item
            for item in system.social.decisions(connection, turn_id)
            if item.character_id == "first"
        )
        assert first.reason_code == "outside_audience"
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 0


def test_task_suspension_and_cancellation_preserve_snapshot(system):
    send(system)
    turn_id = system.planner.plan()[0]
    with system.database.transaction() as connection:
        rows = connection.execute(
            "SELECT * FROM conversation_tasks ORDER BY character_id"
        ).fetchall()
        original = {row["task_id"]: row["snapshot_json"] for row in rows}
        assert system.tasks.suspend_community(connection, "community", datetime.now(UTC)) == 2
        assert all(
            system.tasks.get(connection, row["task_id"])["status"] == "suspended" for row in rows
        )
        system.tasks.resume_community(connection, "community", datetime.now(UTC))
        assert all(
            system.tasks.get(connection, row["task_id"])["snapshot_json"]
            == original[row["task_id"]]
            for row in rows
        )
        system.tasks.cancel_membership(connection, rows[0]["membership_id"], datetime.now(UTC))
        assert not system.completion.update(connection, turn_id, datetime.now(UTC))
        system.tasks.cancel_membership(connection, rows[1]["membership_id"], datetime.now(UTC))
        assert system.completion.update(connection, turn_id, datetime.now(UTC))
    send(system, "取消之后的新输入")
    assert len(system.planner.plan()) == 1


def test_template_and_backend_capabilities_are_intersected(system):
    blueprint = load_blueprint_catalog().blueprint("xiaojin")
    assert CapabilityResolver(frozenset()).tools(blueprint, frozenset({"memory_search"})) == ()
    assert CapabilityResolver(frozenset({"memory_search"})).tools(blueprint, frozenset()) == ()
    assert CapabilityResolver(frozenset({"memory_search"})).tools(
        blueprint, frozenset({"memory_search"})
    ) == ("memory_search",)
