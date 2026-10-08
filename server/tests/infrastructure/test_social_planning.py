from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
from historical_messages import historical_message
from test_message_perspective import build_system

from echo_commons.execution.records import ExecutionRecorder
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
from echo_commons.modules.conversations.tasks.dispatch import ConversationTaskDispatcher
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
        ConversationTaskDispatcher(tasks, context, ExecutionRecorder(base.database)),
        base.perspective,
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


def test_one_turn_prepares_only_selected_snapshot_and_preserves_waiting_candidates(system):
    source = send(system, mentions=(ActorRef("character", "third"),))
    turns = system.planner.plan()
    assert len(turns) == 1
    with system.database.read() as connection:
        decisions = system.social.decisions(connection, turns[0])
        assert {item.character_id for item in decisions if item.status == "selected"} == {
            "third",
        }
        assert {item["character_id"] for item in system.social.waiting(connection, turns[0])} == {
            "first",
            "second",
        }
        rows = connection.execute("SELECT * FROM conversation_tasks").fetchall()
        snapshots = [system.tasks.snapshot(connection, row["task_id"]) for row in rows]
        assert len(snapshots) == 1
        assert {snapshot.scope.character_id for snapshot in snapshots} == {"third"}
        assert all(
            snapshot.scope.observation_upper_sequence == source.sequence for snapshot in snapshots
        )
        assert all(
            snapshot.perspective.inputs[0].message_id == source.message_id for snapshot in snapshots
        )
        chain = system.social.chain(connection, system.social.by_id(connection, turns[0]).chain_id)
        assert chain.task_count == 1 and chain.message_count == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert system.planner.plan() == ()


def test_parallel_planners_cannot_duplicate_turns_tasks_or_snapshots(system):
    send(system)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: system.planner.plan(), range(3)))
    assert sum(len(result) for result in results) == 1
    with system.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM social_turns").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 1


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
    assert len(system.planner.plan()) == 1
    with system.database.read() as connection:
        assert system.tasks.snapshot(connection, task_id) == before
        assert before.self.mood == "平和"
        assert all(
            message.text != "后来的输入"
            for message in before.perspective.inputs + before.perspective.history
        )
        assert len(system.batches.awaiting(connection)) == 0
        assert system.tasks.get(connection, task_id)["status"] == "cancelled"
        new_task = connection.execute(
            "SELECT task_id FROM conversation_tasks WHERE status='pending'"
        ).fetchone()[0]
        new = system.tasks.snapshot(connection, new_task)
        assert new.self.mood == "新情绪"
        assert any(item.text == "后来的输入" for item in new.perspective.inputs)


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


def test_departed_candidate_allows_next_candidate_without_repeating_attempt(system):
    send(system)
    turn_id = system.planner.plan()[0]
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    assert system.planner.plan() == (turn_id,)
    with system.database.read() as connection:
        decisions = system.social.decisions(connection, turn_id)
        assert {item.character_id for item in decisions if item.status == "selected"} == {"second"}
        assert (
            next(item for item in decisions if item.character_id == "first").outcome == "cancelled"
        )
        assert system.social.get(connection, "community", turn_id).status == "running"
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 2


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
        assert system.tasks.suspend_community(connection, "community", datetime.now(UTC)) == 1
        assert all(
            system.tasks.get(connection, row["task_id"])["status"] == "suspended" for row in rows
        )
        system.tasks.resume_community(connection, "community", datetime.now(UTC))
        assert all(
            system.tasks.get(connection, row["task_id"])["snapshot_json"]
            == original[row["task_id"]]
            for row in rows
        )
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    with system.database.read() as connection:
        assert system.social.by_id(connection, turn_id).status == "running"
        assert (
            system.tasks.get(connection, rows[0]["task_id"])["snapshot_json"]
            == original[rows[0]["task_id"]]
        )
    send(system, "取消之后的新输入")
    assert len(system.planner.plan()) == 1


def test_template_and_backend_capabilities_are_intersected(system):
    blueprint = load_blueprint_catalog().blueprint("xiaojin")
    assert CapabilityResolver(frozenset()).tools(blueprint, frozenset({"memory_search"})) == ()
    assert CapabilityResolver(frozenset({"memory_search"})).tools(blueprint, frozenset()) == ()
    assert CapabilityResolver(frozenset({"memory_search"})).tools(
        blueprint, frozenset({"memory_search"})
    ) == ("memory_search",)
