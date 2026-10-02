import shutil
from datetime import UTC, datetime
from importlib.resources import files
from uuid import uuid4

import pytest
from test_memory_sealing import sealing
from test_reflection_context import build_reflection
from test_social_planning import build_planning_system, send

from echo_commons.agents.contracts.output import (
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.conversations.api.schemas import MessageView
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.perspective.contracts import ObservationScope
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.message_sources import SystemSource


def test_existing_turns_messages_and_tasks_survive_status_migration(tmp_path):
    old_sql = tmp_path / "old-sql"
    old_sql.mkdir()
    shutil.copyfile(
        str(files("echo_commons.infrastructure.database.sql").joinpath("0001_initial.sql")),
        old_sql / "0001_initial.sql",
    )
    system = build_planning_system(tmp_path, sql_directory=old_sql)
    message = send(system)
    system.planner.plan()
    with system.database.read() as connection:
        before = {
            table: tuple(tuple(row) for row in connection.execute(f"SELECT * FROM {table}"))
            for table in ("social_turns", "conversation_tasks", "messages", "social_turn_batches")
        }
        assert before["social_turns"] and before["conversation_tasks"]
    assert initialize(system.database) == 2
    assert initialize(system.database) == 2
    with system.database.read() as connection:
        for table, rows in before.items():
            assert tuple(tuple(row) for row in connection.execute(f"SELECT * FROM {table}")) == rows
        assert system.messages.get(connection, "conversation", message.message_id) == message
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        turn_id = connection.execute("SELECT social_turn_id FROM social_turns").fetchone()[0]
    with pytest.raises(StorageError), system.database.transaction() as connection:
        connection.execute(
            "UPDATE social_turns SET status = 'pending' WHERE social_turn_id = ?", (turn_id,)
        )


def test_system_source_is_readable_but_has_no_membership_or_relationship_target(tmp_path):
    system = build_planning_system(tmp_path)
    sender = SystemSource("game-rules")
    with system.database.transaction() as connection:
        conversation = system.conversations.conversations.get(
            connection, "community", "conversation"
        )
        first = system.conversations.conversations.current(
            connection, "conversation", ActorRef("character", "first")
        )
        message = Message(
            str(uuid4()),
            "community",
            "conversation",
            conversation.next_sequence,
            sender,
            None,
            "棋局已开始",
            "recipients",
            (first.membership_id,),
            (),
            None,
            None,
            None,
            None,
            str(uuid4()),
            datetime.now(UTC),
        )
        system.messages.add(connection, message)
        connection.execute(
            "UPDATE conversations SET next_sequence = next_sequence + 1 "
            "WHERE conversation_id = 'conversation'"
        )
        assert system.messages.get(connection, "conversation", message.message_id) == message
        assert system.world.observe(
            connection,
            ObservationScope(
                "community", "conversation", ActorRef("character", "first"), message.sequence
            ),
        ).messages == (message,)
        assert (
            system.world.observe(
                connection,
                ObservationScope(
                    "community", "conversation", ActorRef("character", "second"), message.sequence
                ),
            ).messages
            == ()
        )
        encoded = MessageView.model_validate(
            {
                "message_id": message.message_id,
                "conversation_id": "conversation",
                "sequence": message.sequence,
                "sender": sender,
                "text": message.text,
                "visibility": message.visibility,
                "mentions": (),
                "reply_to_message_id": None,
                "source_turn_id": None,
                "created_at_utc": message.created_at_utc,
            }
        ).model_dump_json()
        assert MessageView.model_validate_json(encoded).sender == sender
    send(system, mentions=(ActorRef("character", "first"),))
    system.planner.plan()
    with system.database.read() as connection:
        task = connection.execute(
            "SELECT task_id FROM conversation_tasks WHERE character_id = 'first'"
        ).fetchone()[0]
        snapshot = system.tasks.snapshot(connection, task)
        outputs = OutputRegistry()
        outputs.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
        prompt = project_snapshot(
            snapshot, output_contract=CHARACTER_MESSAGE_CONTRACT, outputs=outputs
        )
        assert "system:game-rules" in str(prompt.messages)
        assert all(isinstance(item.target, ActorRef) for item in snapshot.self.relationships)
    segment = sealing(system).seal("community", "first", "conversation")
    _, coordinator = build_reflection(system)
    graph = coordinator.start_segment("community", "first", segment.segment_id)
    with system.database.read() as connection:
        snapshot = coordinator.runs.snapshot(
            connection, "community", "first", str(graph.graph_run_id)
        )
        assert sender not in source_actors(snapshot)
    with pytest.raises(ValueError):
        ActorRef("system", "game-rules")
