import shutil
from dataclasses import replace
from importlib.resources import files

import pytest
from echo_games.public import ResignGameCommand
from fastapi.testclient import TestClient
from support.activities import activity_game, message, prepare
from support.application import settings_for
from support.migrations import load_history

from echo_commons.agents.contracts.activity import (
    ActivityUnderstanding,
    IntentProposal,
    MessageUnderstanding,
)
from echo_commons.app.main import create_app
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, IdempotencyConflict, NotFoundError


def test_intents_preserve_source_require_versions_and_pin_accepted_chat(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    with TestClient(create_app(settings)) as client:
        game = activity_game(client)
        source = message(client, game, "我们比一比谁能占住边线，好不好？")
        frozen = prepare(client, game, input_id="intent")
        app = client.app.state.application
        proposals = (
            IntentProposal(content="试着在边线争取主动", message_ids=(source.message_id,)),
        )
        memory = app.activity_working_memory.replace(
            "community", "first", "intent", expected_version=0, intents=proposals
        )
        assert memory.version == 1
        assert memory.intents[0].source_input_id == "intent"
        assert (
            app.activity_working_memory.replace(
                "community", "first", "intent", expected_version=0, intents=proposals
            )
            == memory
        )
        with pytest.raises(IdempotencyConflict):
            app.activity_working_memory.replace(
                "community", "first", "intent", expected_version=0, intents=()
            )
        with pytest.raises(NotFoundError):
            app.activity_working_memory.replace(
                "community", "second", "intent", expected_version=0, intents=proposals
            )
        app.activity_context.record_understanding(
            "community",
            "first",
            "intent",
            ActivityUnderstanding(
                messages=(
                    MessageUnderstanding(
                        message_id=source.message_id, interpretation="邀请比试边线"
                    ),
                ),
                event_ids=tuple(e.event_id for e in frozen.material.game.events),
            ),
        )
        app.activity_context.conversation.policy = replace(
            app.activity_context.conversation.policy,
            recent_message_max_chars=1,
        )
        later = message(client, game, "那继续吧。")
        next_input = prepare(client, game, input_id="next")
        assert next_input.material.working_memory == memory
        assert next_input.material.conversation.perspective.trigger_message_ids == (
            later.message_id,
        )
        assert source.message_id in {
            m.message_id for m in next_input.material.conversation.perspective.inputs
        }
        with pytest.raises(ConflictError):
            app.activity_working_memory.replace(
                "community", "first", "next", expected_version=0, intents=proposals
            )
        with app.database.read() as connection:
            assert app.activity_working_memory.current_in(connection, frozen.scope) == memory
            assert not connection.execute(
                "SELECT * FROM memory_search_fts WHERE display_text LIKE '%试着在边线争取主动%'"
            ).fetchall()
        app.communities.update("community", expected_version=1, status="paused")
        with app.database.read() as connection:
            assert app.activity_working_memory.current_in(connection, frozen.scope) == memory
    with TestClient(create_app(settings)) as client:
        app = client.app.state.application
        with app.database.read() as connection:
            assert app.activity_working_memory.current_in(connection, frozen.scope) == memory
        app.communities.update("community", expected_version=2, status="active")
        unchanged = prepare(client, game)
        assert unchanged.material.working_memory == memory
        cleared = app.activity_working_memory.replace(
            "community", "first", unchanged.snapshot_id, expected_version=1, intents=()
        )
        assert not cleared.intents and cleared.version == 2


def test_unchanged_intents_keep_identity_and_version_until_content_or_sources_change(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        game = activity_game(client)
        first = message(client, game, "试试边线吧。")
        second = message(client, game, "我想看你怎么封堵。")
        app = client.app.state.application
        initial = prepare(client, game)
        targets = (
            IntentProposal(content="尝试边线", message_ids=(first.message_id, second.message_id)),
            IntentProposal(content="观察对方的威胁"),
        )
        saved = app.activity_working_memory.replace(
            "community", "first", initial.snapshot_id, expected_version=0, intents=targets
        )
        next_input = prepare(client, game)
        same = app.activity_working_memory.replace(
            "community",
            "first",
            next_input.snapshot_id,
            expected_version=1,
            intents=(
                targets[1],
                IntentProposal(
                    content=" 尝试边线 ",
                    message_ids=(second.message_id, first.message_id, first.message_id),
                ),
                targets[1],
            ),
        )
        assert same.version == saved.version and same.intents == saved.intents
        assert same.last_input_id == next_input.snapshot_id
        changed_input = prepare(client, game)
        changed = app.activity_working_memory.replace(
            "community",
            "first",
            changed_input.snapshot_id,
            expected_version=1,
            intents=(
                targets[1],
                IntentProposal(content="尝试边线", message_ids=(first.message_id,)),
            ),
        )
        assert changed.version == 2
        assert changed.intents[0] == saved.intents[1]
        assert changed.intents[1].intent_id != saved.intents[0].intent_id
        assert changed.intents[1].source_input_id == changed_input.snapshot_id


def test_finished_game_excludes_intents_and_explicit_clear_preserves_old_input(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        game = activity_game(client)
        message(client, game, "我想挑战边线。")
        frozen = prepare(client, game, input_id="before-finish")
        app = client.app.state.application
        app.activity_working_memory.replace(
            "community",
            "first",
            frozen.snapshot_id,
            expected_version=0,
            intents=(IntentProposal(content="考虑边线的进攻"),),
        )
        before = prepare(client, game, input_id="with-intent")
        assert before.material.working_memory.intents
        with app.database.read() as connection:
            access = app.game_participation.seat_access(
                connection, ActorRef("player", "alice"), game
            )
        app.game_participation.resign_game(
            ActorRef("player", "alice"),
            ResignGameCommand(
                game_id=game,
                request_id="resign",
                expected_state_version=before.material.game.state_version,
                participation_id=access.participation_id,
            ),
        )
        message(client, game, "这局结束了，下次再来。")
        after = prepare(client, game)
        assert after.material.game.status == "finished"
        assert not after.material.working_memory.intents
        assert not after.material.private_thoughts
        with app.database.transaction() as connection:
            app.activity_working_memory.clear_in(connection, before.scope)
        with app.database.read() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM activity_working_memory").fetchone()[0]
                == 0
            )
        assert app.activity_context.restore("community", "first", "with-intent") == before


def test_unknown_message_reference_rejected_and_cleanup_handles_new_records(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        game = activity_game(client)
        source = message(client, game, "约定边线见。")
        frozen = prepare(client, game)
        app = client.app.state.application
        with pytest.raises(ValueError, match="visible"):
            app.activity_working_memory.replace(
                "community",
                "first",
                frozen.snapshot_id,
                expected_version=0,
                intents=(IntentProposal(content="继续考虑", message_ids=("unseen",)),),
            )
        app.activity_working_memory.replace(
            "community",
            "first",
            frozen.snapshot_id,
            expected_version=0,
            intents=(IntentProposal(content="继续考虑", message_ids=(source.message_id,)),),
        )
        app.communities.update("community", expected_version=1, status="paused")
        response = client.post(
            "/internal/maintenance/cleanup", json={"community_ids": ["community"], "dry_run": False}
        )
        assert response.status_code == 200, response.text
        assert response.json()["deleted"]
        with app.database.read() as connection:
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
            assert connection.execute("SELECT COUNT(*) FROM activity_inputs").fetchone()[0] == 0


def test_version_29_upgrade_preserves_populated_database(tmp_path):
    scripts = tmp_path / "version29"
    scripts.mkdir()
    for item in files("echo_commons.infrastructure.database.sql").iterdir():
        if item.name.endswith(".sql") and int(item.name.split("_", 1)[0]) <= 29:
            shutil.copyfile(str(item), scripts / item.name)
    database = load_history(19, tmp_path / "history.sqlite3")
    assert initialize(database, sql_directory=scripts) == 29
    with database.read() as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            if row[0] != "schema_migrations"
        ]
        before = {
            table: [tuple(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
            for table in tables
        }
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] > 0
    assert initialize(database) == initialize(database) == 35
    with database.read() as connection:
        assert before == {
            table: [
                tuple(row)[: len(before[table][0])] if before[table] else tuple(row)
                for row in connection.execute(f'SELECT * FROM "{table}"')
            ]
            for table in tables
        }
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        for table in (
            "activity_inputs",
            "activity_working_memory",
            "activity_observation_progress",
            "activity_persona_projections",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
