import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from echo_commons.execution.records import ExecutionRecorder
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.characters.domain.instance import AvailabilityStatus
from echo_commons.modules.characters.domain.relationship import (
    RelationshipEvidence,
    RelationshipKey,
    RelationshipState,
)
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.bootstrap import CharacterBootstrap
from echo_commons.modules.characters.services.state import CharacterStateService
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog
from echo_commons.modules.communities.domain import CommunityStatus
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.communities.service import CommunityService
from echo_commons.modules.conversations.domain.conversation import ConversationKind
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.services.conversation import ConversationService
from echo_commons.modules.conversations.tasks.dispatch import TaskCancellation
from echo_commons.modules.conversations.tasks.lifecycle import TaskLifecycle
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.services.bootstrap import MemoryBootstrap
from echo_commons.modules.memory.services.indexing import MemoryIndexing
from echo_commons.modules.perspective.conversation import ConversationPerspective
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.lifecycle import SocialLifecycle
from echo_commons.modules.social.repository import SocialRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, NotFoundError


@pytest.fixture
def system(tmp_path):
    database = Database(tmp_path / "baseline.sqlite3")
    initialize(database)
    communities = CommunityRepository()
    lifecycle = TaskLifecycle(
        ConversationTaskRepository(),
        TurnCompletion(SocialRepository()),
        ExecutionRecorder(database),
        SocialLifecycle(
            SocialRepository(),
            TurnCompletion(SocialRepository()),
            TaskCancellation(ExecutionRecorder(database)),
        ),
    )
    community_service = CommunityService(database, communities, lifecycle)
    instances, states = InstanceRepository(), StateRepository()
    conversation_repo, message_repo = ConversationRepository(), MessageRepository()
    entries = MemoryEntryRepository()
    index = MemoryIndexing(
        instances,
        conversation_repo,
        ConversationPerspective(communities, conversation_repo, message_repo),
        SearchRepository(),
        entries,
    )
    characters = CharacterBootstrap(
        database,
        load_blueprint_catalog(),
        communities,
        instances,
        states,
        MemoryBootstrap(entries, index, communities),
    )
    conversations = ConversationService(database, communities, conversation_repo, lifecycle)
    community_service.create("社群", "Asia/Shanghai", community_id="community")
    community_service.register_player("玩家", player_id="player")
    community_service.join("community", ActorRef("player", "player"))
    return database, community_service, characters, conversations


def test_empty_initialization_is_repeatable_and_has_exact_tables(tmp_path):
    database = Database(tmp_path / "new.sqlite3")
    assert initialize(database) == initialize(database) == 11
    with database.read() as connection:
        names = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        explicit = names - {name for name in names if name.startswith("memory_search_fts_")}
        assert len(explicit) == 65
        assert "thought_provenance" not in names and "meta" not in names
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM communities").fetchone()[0] == 0


def test_parallel_initialization_uses_one_atomic_migration(tmp_path):
    database = Database(tmp_path / "concurrent.sqlite3")
    with ThreadPoolExecutor(max_workers=3) as executor:
        assert list(executor.map(lambda _: initialize(database), range(3))) == [11, 11, 11]
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 11


def test_failed_migration_rolls_back_tables_and_version(tmp_path):
    sql = tmp_path / "sql"
    sql.mkdir()
    (sql / "0001_initial.sql").write_text(
        "CREATE TABLE valid (id TEXT);\nCREATE TABLE broken (id TEXT,);\n", encoding="utf-8"
    )
    database = Database(tmp_path / "failed.sqlite3")
    with pytest.raises(sqlite3.OperationalError):
        initialize(database, sql_directory=sql)
    with database.read() as connection:
        assert (
            connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'valid'").fetchone()
            is None
        )
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0


def test_same_blueprint_creates_independent_instances_and_preload(system):
    database, _, characters, _ = system
    first = characters.create("community", "xiaojin", character_id="first")
    second = characters.create("community", "xiaojin", character_id="second")
    assert first.character_id != second.character_id
    assert characters.create("community", "xiaojin", character_id="first") == first
    with database.read() as connection:
        rows = connection.execute(
            "SELECT character_id, memory_id, subject_id, visibility FROM memory_entries"
        ).fetchall()
        assert len(rows) == 8
        assert len({row["memory_id"] for row in rows}) == 8
        assert all(row["subject_id"] == row["character_id"] for row in rows)
        indexed = connection.execute(
            "SELECT character_id, source_id FROM memory_search_documents "
            "WHERE source_kind = 'memory_entry'"
        ).fetchall()
        assert {(row["character_id"], row["source_id"]) for row in indexed} == {
            (row["character_id"], row["memory_id"])
            for row in rows
            if row["visibility"] in ("resident", "recallable")
        }
        assert connection.execute("SELECT COUNT(*) FROM character_state_entries").fetchone()[0] == 6
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_foreign_community_identity_is_rejected(system):
    database, communities, characters, conversations = system
    characters.create("community", "xiaojin", character_id="character")
    communities.create("另一社群", "UTC", community_id="other")
    with pytest.raises(NotFoundError):
        communities.join("other", ActorRef("character", "character"))
    with pytest.raises(ConflictError):
        characters.create("other", "xiaojin", character_id="character")
    with database.transaction() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO character_state_entries VALUES ('illegal', 'other', "
            "'character', 'mood', '', 'initialization', 'bad', 2, "
            "'2026-10-01T00:00:00+00:00', NULL)"
        )
    with pytest.raises(NotFoundError):
        conversations.create("other", ConversationKind.GROUP, (ActorRef("character", "character"),))


def test_membership_rejoining_has_new_identity_and_preserves_history(system):
    database, _, characters, conversations = system
    characters.create("community", "xiaojin", character_id="character")
    actors = (ActorRef("player", "player"), ActorRef("character", "character"))
    conversation = conversations.create("community", ConversationKind.GROUP, actors)
    with database.read() as connection:
        original = conversations.conversations.current(
            connection, conversation.conversation_id, actors[1]
        )
    left = conversations.leave("community", conversation.conversation_id, actors[1])
    rejoined = conversations.join("community", conversation.conversation_id, actors[1])
    assert left.membership_id == original.membership_id
    assert rejoined.membership_id != original.membership_id
    assert left.left_at_sequence == rejoined.joined_after_sequence == 0
    with database.read() as connection:
        assert (
            len(
                conversations.conversations.members(
                    connection, conversation.conversation_id, current_only=False
                )
            )
            == 3
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_direct_conversation_uses_shared_member_rule(system):
    _, _, characters, conversations = system
    characters.create("community", "xiaojin", character_id="character")
    actors = (ActorRef("player", "player"), ActorRef("character", "character"))
    created = conversations.create("community", ConversationKind.DIRECT, actors)
    with pytest.raises(ValueError):
        conversations.create("community", ConversationKind.DIRECT, (actors[0],))
    characters.create("community", "xiaojin", character_id="third")
    with pytest.raises(ValueError):
        conversations.join("community", created.conversation_id, ActorRef("character", "third"))


def test_latest_expired_state_does_not_restore_old_value(system):
    database, _, characters, _ = system
    characters.create("community", "xiaojin", character_id="character")
    service = CharacterStateService(database, InstanceRepository(), StateRepository())
    expiry = datetime.now(UTC) + timedelta(seconds=10)
    entry = service.record(
        "community",
        "character",
        StateKind.MOOD,
        "开心",
        "reviewed_result",
        "result",
        expected_version=1,
        expires_at=expiry,
    )
    assert (
        service.record(
            "community",
            "character",
            StateKind.MOOD,
            "开心",
            "reviewed_result",
            "result",
            expected_version=1,
            expires_at=expiry,
        )
        == entry
    )
    with database.read() as connection:
        assert (
            service.states.latest(
                connection, "character", StateKind.MOOD, expiry + timedelta(seconds=1)
            )
            is None
        )
    with pytest.raises(ConflictError):
        service.record(
            "community",
            "character",
            StateKind.MOOD,
            "平静",
            "reviewed_result",
            "another",
            expected_version=1,
        )


def test_failed_transaction_does_not_leave_partial_identity(system):
    database, _, _, _ = system
    with pytest.raises(StorageError) as failure, database.transaction() as connection:
        connection.execute(
            "INSERT INTO players VALUES ('rollback', '回滚玩家', '2026-10-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO community_members VALUES ('missing', 'player', 'rollback', "
            "'2026-10-01T00:00:00+00:00')"
        )
    assert isinstance(failure.value.__cause__, sqlite3.IntegrityError)
    assert failure.value.code == "sqlite_constraint_foreignkey"
    with database.read() as connection:
        assert (
            connection.execute("SELECT 1 FROM players WHERE player_id = 'rollback'").fetchone()
            is None
        )


def test_community_and_availability_only_increment_on_change(system):
    database, communities, characters, _ = system
    character = characters.create("community", "xiaojin")
    with database.read() as connection:
        original = communities.repository.get(connection, "community")
    assert communities.update("community", expected_version=0).state_version == 0
    assert original.status is CommunityStatus.PAUSED
    active = communities.update("community", expected_version=0, status=CommunityStatus.ACTIVE)
    assert active.state_version == 1
    assert (
        communities.update("community", expected_version=1, status=CommunityStatus.ACTIVE) == active
    )
    with pytest.raises(ConflictError):
        communities.update("community", expected_version=0, status=CommunityStatus.ACTIVE)
    with pytest.raises(ValueError):
        communities.update(
            "community",
            expected_version=1,
            world_time=original.world_time_utc - timedelta(seconds=1),
        )
    states = CharacterStateService(database, InstanceRepository(), StateRepository())
    assert (
        states.set_availability(
            "community", character.character_id, AvailabilityStatus.AVAILABLE, expected_version=0
        )
        == character
    )
    busy = states.set_availability(
        "community",
        character.character_id,
        AvailabilityStatus.BUSY,
        expected_version=0,
        reason="正在参与活动",
    )
    assert busy.availability_version == 1
    with pytest.raises(ConflictError):
        states.set_availability(
            "community", character.character_id, AvailabilityStatus.AVAILABLE, expected_version=0
        )


def test_relationship_storage_enforces_directed_scope(system):
    database, communities, characters, _ = system
    first = characters.create("community", "xiaojin")
    second = characters.create("community", "xiaojin")
    repository = RelationshipRepository()
    now = datetime.now(UTC)
    player_key = RelationshipKey("community", first.character_id, "player", "player")
    character_key = RelationshipKey(
        "community", first.character_id, "character", second.character_id
    )
    with database.transaction() as connection:
        for key in (player_key, character_key):
            state = RelationshipState.stranger(key, updated_at_utc=now)
            repository.save(connection, state)
            assert repository.get(connection, key, now) == state
            evidence = RelationshipEvidence(
                uuid4(), key, "interaction", "message", "source", now, now
            )
            repository.add_evidence(connection, evidence)
            assert repository.evidence(connection, key, "message", "source") == evidence
        assert connection.execute("SELECT COUNT(*) FROM relationship_state").fetchone()[0] == 2
    communities.create("另一个社群", "UTC", community_id="other")
    with pytest.raises(StorageError) as failure, database.transaction() as connection:
        invalid = RelationshipKey("other", first.character_id, "player", "player")
        repository.save(connection, RelationshipState.stranger(invalid, updated_at_utc=now))
    assert isinstance(failure.value.__cause__, sqlite3.IntegrityError)
