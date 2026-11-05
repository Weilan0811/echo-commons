from functools import partial
from uuid import uuid4

import pytest
from echo_games.public import AeroplaneView, MovePlaneAction
from fastapi.testclient import TestClient
from support.activities import prepare
from support.application import settings_for
from support.games import operation, view
from support.http import create_group
from test_activity_models import decision_settings

from echo_commons.agents.contracts.activity import ActivityUnderstanding
from echo_commons.app.main import create_app
from echo_commons.modules.activities.gameplay.contracts import AnalysisRequest


def create_match(client):
    create_group(client, memory_mode="simple")
    response = client.post(
        "/api/games",
        json={
            "player_id": "alice",
            "community_id": "community",
            "request_id": uuid4().hex,
            "game_type": "aeroplane",
            "ruleset_id": "aeroplane.traditional",
            "ruleset_version": 1,
            "initial_seat_id": "red",
        },
    )
    assert response.status_code == 201, response.text
    game = response.json()["game_id"]
    for seat, character in (("yellow", "first"), ("blue", "second")):
        operation(
            client,
            game,
            "participants",
            seat_id=seat,
            participant={"kind": "character", "character_id": character},
        )
    operation(client, game, "start")
    return game


def player_move(client, game):
    app = client.app.state.application
    observed = AeroplaneView.model_validate(view(client, game))
    analysis = client.portal.call(
        app.game_analysis.analyze,
        AnalysisRequest(view=observed, opportunity=observed.opportunities[0]),
    )
    selected = next(
        c.action for c in analysis.candidates if c.candidate_id == analysis.recommended_candidate_id
    )
    response = client.post(
        f"/api/games/{game}/actions",
        json={
            "player_id": "alice",
            "request_id": uuid4().hex,
            "opportunity_id": observed.opportunities[0].opportunity_id,
            "expected_state_version": observed.state_version,
            "action": selected.model_dump(),
        },
    )
    assert response.status_code == 200, response.text


def current_character(client, game):
    observed = view(client, game)
    return {"yellow": "first", "blue": "second"}.get(observed["state"]["current_seat_id"])


def test_multi_character_automatic_roll_and_union_input_survive_restart(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    settings = settings.model_copy(
        update={"activity": settings.activity.model_copy(update={"input_max_chars": 24000})}
    )
    with TestClient(create_app(settings)) as client:
        game = create_match(client)
        app = client.app.state.application
        app.games.registry.resolve("aeroplane", "aeroplane.traditional", 1)._random.seed(0)
        for _ in range(150):
            character = current_character(client, game)
            if character is None:
                player_move(client, game)
                continue
            app.activity_coordinator.scan()
            with app.database.read() as connection:
                task = connection.execute(
                    "SELECT * FROM activity_tasks WHERE status='pending' AND purpose='turn'"
                ).fetchone()
            assert task is not None
            if task["mode"] == "automatic":
                client.portal.call(app.supervisor.workers["activities-0"].run_once)
                continue
            frozen = prepare(client, game, kind="turn", character=character, input_id="union")
            selected = frozen.analysis.candidates[0].action
            suggested = client.portal.call(
                partial(
                    app.activity_context.prepare_turn,
                    "community",
                    character,
                    game,
                    input_id="suggested",
                    suggested_actions=(selected,),
                )
            )
            assert any("suggestion" in c.origins for c in suggested.analysis.candidates)
            exact = frozen.model_dump_json()
            assert frozen.material.game.has_more_events
            app.activity_context.record_understanding(
                "community",
                character,
                "union",
                ActivityUnderstanding(
                    messages=(),
                    event_ids=tuple(e.event_id for e in frozen.material.game.events),
                    thought="记录这批真实观察，剩余事件留给后续判断。",
                ),
            )
            assert app.activity_context.pending_sources("community", character, game)["event_ids"]
            break
        else:
            pytest.fail("No real multi-choice opportunity appeared")
    with TestClient(create_app(settings)) as client:
        app = client.app.state.application
        assert (
            app.activity_context.restore("community", character, "union").model_dump_json() == exact
        )
        assert not isinstance(selected, MovePlaneAction) or selected.plane_id in range(1, 5)


@pytest.mark.model
@pytest.mark.parametrize("local", [False, True], ids=["ordinary", "local"])
def test_two_characters_make_real_aeroplane_choices(tmp_path, local, record_testsuite_property):
    settings = decision_settings(tmp_path) if local else settings_for(tmp_path, workers=False)
    settings = settings.model_copy(
        update={"debug_capture_enabled": True, "debug_capture_path": str(tmp_path / "captures")}
    )
    with TestClient(create_app(settings)) as client:
        game = create_match(client)
        app = client.app.state.application
        app.games.registry.resolve("aeroplane", "aeroplane.traditional", 1)._random.seed(552)
        completed = set()
        for _step in range(250):
            character = current_character(client, game)
            if character is None:
                player_move(client, game)
            else:
                client.portal.call(app.supervisor.workers["activities-0"].run_once)
                with app.database.read() as connection:
                    failures = [
                        dict(r)
                        for r in connection.execute(
                            "SELECT task_id,last_error_code FROM activity_tasks "
                            "WHERE status='failed'"
                        )
                    ]
                    assert not failures, failures
                    completed = {
                        r[0]
                        for r in connection.execute(
                            "SELECT DISTINCT character_id FROM activity_tasks "
                            "WHERE status='completed' AND mode!='automatic' AND purpose='turn'"
                        )
                    }
            if completed == {"first", "second"}:
                break
        else:
            pytest.fail("Both characters did not complete their choices")
        record_testsuite_property("choice_count", len(completed))
        record_testsuite_property("steps", _step + 1)
