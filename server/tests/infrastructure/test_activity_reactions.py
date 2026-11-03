import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from echo_games.public import (
    GameError,
    PlaceStoneAction,
    observe_gomoku_tactics,
    read_gomoku_tactics,
)
from fastapi.testclient import TestClient
from support.activities import activity_game, message
from support.activity_actions import CHARACTER, play_in
from support.application import settings_for
from support.games import operation

from echo_commons.app.main import create_app
from echo_commons.modules.activities.policy import ReactionPolicy
from echo_commons.shared.actors import ActorRef


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        yield client


@pytest.mark.parametrize(
    ("significance", "silence", "count", "expected"),
    [
        (0.75, 60, 0, 0.6625),
        (0.75, 60, 2, 0.33125),
        (0, 60, 0, 0.25),
        (0, 0, 0, 0),
        (1, 900, 0, 0.9),
    ],
)
def test_probability_formula(significance, silence, count, expected):
    assert ReactionPolicy().probability(significance, silence, count) == pytest.approx(expected)


def finish(client, game):
    app = client.app.state.application
    with app.database.read() as connection:
        access = app.game_queries.participant_context(
            connection, "community", ActorRef("player", "alice"), game
        ).access
    operation(client, game, "resign", participation_id=access.participation_id)


def test_off_turn_observation_does_not_grant_action_preview(client):
    game = activity_game(client)
    app = client.app.state.application
    with app.database.transaction() as connection:
        play_in(app, connection, game, CHARACTER, PlaceStoneAction(x=8, y=8))
    observed = app.game_observations.observe("community", "first", game)
    assert not observed.view.opportunities
    assert observe_gomoku_tactics(observed.view).winning_actions == ()
    with pytest.raises(GameError, match="current actor"):
        read_gomoku_tactics(observed.view)


def test_parallel_scanners_share_one_settlement_draw(client):
    game = activity_game(client)
    finish(client, game)
    app = client.app.state.application
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = tuple(workers.map(lambda _: app.activity_reactions.scan(), range(2)))
    assert sum(len(result) for result in results) == 1
    with app.database.read() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM activity_reaction_opportunities").fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM conversation_initiations").fetchone()[0] == 1
        )


def test_archiving_ends_deferred_event_opportunity(client):
    game = activity_game(client)
    finish(client, game)
    app = client.app.state.application
    message(client, game, "等等，我想先问一下刚才那步。")
    app.planner.plan()
    assert app.activity_reactions.scan() == ()
    operation(client, game, "end", expected_conversation_version=1)
    with app.database.read() as connection:
        assert (
            connection.execute("SELECT status FROM activity_reaction_opportunities").fetchone()[0]
            == "cancelled"
        )


def test_actual_settlement_arranges_one_request_and_reuses_it(client):
    game = activity_game(client)
    finish(client, game)
    app = client.app.state.application
    (source,) = app.activity_reactions.scan()
    assert app.activity_reactions.scan() == ()
    with app.database.read() as connection:
        opportunity = connection.execute("SELECT * FROM activity_reaction_opportunities").fetchone()
        assert opportunity["kind"] == "settlement" and opportunity["probability"] == 1
        assert opportunity["source_id"] == source and opportunity["status"] == "arranged"
        assert (
            connection.execute("SELECT COUNT(*) FROM conversation_initiations").fetchone()[0] == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM activity_task_sources").fetchone()[0] == 1
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    (identity,) = app.activity_coordinator.scan()
    with app.database.read() as connection:
        task = app.activity_queue.repository.get(connection, identity)
        assert task["purpose"] == "reply"


def test_player_reply_defers_settlement_without_consuming_probability(client):
    game = activity_game(client)
    finish(client, game)
    app = client.app.state.application
    message(client, game, "刚才那步我没看明白，你可以解释一下吗？")
    app.planner.plan()
    assert app.activity_reactions.scan() == ()
    with app.database.read() as connection:
        opportunity = connection.execute("SELECT * FROM activity_reaction_opportunities").fetchone()
        assert opportunity["status"] == "pending" and opportunity["sample"] is None


def test_quiet_opportunity_enters_existing_activity_coordination(client):
    activity_game(client)
    app = client.app.state.application
    app.activity_reactions.policy = ReactionPolicy(
        quiet_seconds=0.04,
        minimum_gap_seconds=0,
        base_probability=0,
        significance_weight=0,
        quiet_weight=0,
    )
    app.activity_reactions.scan()
    app.activity_reactions.policy = app.activity_reactions.policy.model_copy(
        update={
            "base_probability": 1,
            "maximum_probability": 1,
            "recency_saturation_seconds": 0.001,
        }
    )
    time.sleep(0.05)
    (source,) = app.activity_reactions.scan()
    assert app.activity_reactions.scan() == ()
    (identity,) = app.activity_coordinator.scan()
    with app.database.read() as connection:
        opportunity = connection.execute(
            "SELECT * FROM activity_reaction_opportunities WHERE kind='quiet'"
        ).fetchone()
        assert opportunity["source_id"] == source and opportunity["status"] == "arranged"
        task = app.activity_queue.repository.get(connection, identity)
        assert (
            connection.execute(
                "SELECT task_id FROM activity_task_sources WHERE source_id=?", (source,)
            ).fetchone()[0]
            == identity
        )
        assert task["purpose"] == "turn"


def test_quiet_opportunity_uses_real_time_and_is_drawn_once(client):
    activity_game(client)
    app = client.app.state.application
    app.activity_reactions.policy = ReactionPolicy(
        quiet_seconds=0.02,
        minimum_gap_seconds=0,
        base_probability=0,
        significance_weight=0,
        quiet_weight=0,
    )
    assert app.activity_reactions.scan() == ()
    time.sleep(0.03)
    assert app.activity_reactions.scan() == ()
    with app.database.read() as connection:
        rows = [
            dict(r)
            for r in connection.execute(
                "SELECT * FROM activity_reaction_opportunities ORDER BY created_at_utc"
            )
        ]
        assert [r["kind"] for r in rows] == ["events", "quiet"]
        assert all(r["status"] == "skipped" and r["sample"] is not None for r in rows)
    assert app.activity_reactions.scan() == ()
    with app.database.read() as connection:
        assert [
            dict(r)
            for r in connection.execute(
                "SELECT * FROM activity_reaction_opportunities ORDER BY created_at_utc"
            )
        ] == rows
