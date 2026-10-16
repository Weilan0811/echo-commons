import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from echo_games.gomoku.contracts import (
    GomokuActionReceipt,
    GomokuDecisionInput,
    GomokuEventBatch,
    GomokuGame,
    GomokuOperationReceipt,
    GomokuView,
)
from echo_games.public import (
    CreateGameCommand,
    GameListQuery,
    GameReadAccess,
    GameService,
    GomokuConfig,
    GomokuCreateGameCommand,
    GomokuResult,
    GomokuState,
    GomokuSubmitActionCommand,
    PlaceStoneAction,
    ResignGameCommand,
    StonePlacedResult,
    SubmitActionCommand,
    default_registry,
)


def test_core_modules_do_not_import_game_implementations():
    source = Path(__file__).resolve().parents[1] / "src/echo_games"
    registry = default_registry()
    implementation_modules = {
        type(
            registry.resolve(item.game_type, rule.ruleset_id, rule.ruleset_version)
        ).__module__.rsplit(".", 1)[0]
        for item in registry.list_game_types()
        for rule in item.rulesets
    }
    for name in ("domain", "contracts", "registry", "repository", "service"):
        tree = ast.parse((source / f"{name}.py").read_text(encoding="utf-8"))
        imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ]
        assert not any(
            module and (module == namespace or module.startswith(namespace + "."))
            for module in imports
            for namespace in implementation_modules
        )
    assert all(
        CreateGameCommand.model_fields[name].is_required()
        for name in ("game_type", "ruleset_id", "ruleset_version", "initial_seat_id", "config")
    )


def test_gameplay_specializes_every_view_and_persisted_action(running):
    service, connection, (black, white) = running
    game = service.repository.game(connection, black.game_id)
    assert type(game) is GomokuGame
    assert type(game.config) is GomokuConfig
    assert type(game.state) is GomokuState
    view = service.read_view(connection, black)
    assert type(view) is GomokuView
    assert GomokuView.model_validate_json(view.model_dump_json()) == view
    decision = service.read_decision_input(connection, black, view.opportunities[0].opportunity_id)
    assert type(decision) is GomokuDecisionInput
    assert type(decision.opportunity.legal_actions[0]) is PlaceStoneAction
    command = GomokuSubmitActionCommand(
        request_id="placed",
        expected_state_version=view.state_version,
        opportunity_id=view.opportunities[0].opportunity_id,
        action=PlaceStoneAction(x=7, y=8),
    )
    receipt = service.submit_action(connection, black, command)
    assert type(receipt) is GomokuActionReceipt
    assert type(receipt.result) is StonePlacedResult
    assert GomokuActionReceipt.model_validate_json(receipt.model_dump_json()) == receipt
    restarted = GameService(default_registry())
    loaded = restarted.read_receipt(connection, black, "placed")
    assert type(loaded) is GomokuActionReceipt
    assert type(loaded.result) is StonePlacedResult
    assert (loaded.result.x, loaded.result.y) == (7, 8)
    assert type(restarted.read_view(connection, white).state) is GomokuState
    events = restarted.read_events(connection, black)
    assert type(events) is GomokuEventBatch
    assert type(events.items[-1].data) is StonePlacedResult
    assert GomokuEventBatch.model_validate_json(events.model_dump_json()) == events


def test_final_results_survive_typed_receipts_events_and_heterogeneous_lists(running):
    service, connection, (black, white) = running
    receipt = service.resign_game(
        connection,
        "bob",
        ResignGameCommand(
            game_id=black.game_id,
            request_id="resign",
            expected_state_version=3,
            participation_id=white.participation_id,
        ),
    )
    assert type(receipt) is GomokuOperationReceipt
    assert type(receipt.result.result) is GomokuResult
    assert GomokuOperationReceipt.model_validate_json(receipt.model_dump_json()) == receipt
    loaded = service.read_operation(connection, "bob", black.game_id, "resign")
    assert type(loaded.result.result) is GomokuResult
    events = service.read_events(connection, black)
    assert type(events.items[-1].data.result) is GomokuResult
    assert GomokuEventBatch.model_validate_json(events.model_dump_json()) == events
    listed = service.list_games(connection, GameListQuery(game_ids=(black.game_id,)))
    payload = json.loads(listed.model_dump_json())
    assert payload["items"][0]["result"] == {"reason": "resignation", "winner_seat_id": "black"}
    assert (
        type(
            service.read_game(
                connection,
                GameReadAccess(
                    game_id=black.game_id,
                    requester_ref="alice",
                ),
            ).result
        )
        is GomokuResult
    )


def test_registry_rejects_a_config_of_the_wrong_model_before_writing(system):
    service, connection = system
    wrong = CreateGameCommand[GomokuState](
        request_id="wrong-config",
        game_type="gomoku",
        ruleset_id="gomoku.freestyle",
        ruleset_version=1,
        initial_seat_id="black",
        config=GomokuState(),
    )
    with pytest.raises(ValidationError):
        service.create_game(connection, "alice", wrong)
    assert connection.execute("SELECT COUNT(*) FROM game_games").fetchone()[0] == 0


def test_registry_rejects_a_wrong_action_without_consuming_the_opportunity(running):
    service, connection, (black, _) = running
    view = service.read_view(connection, black)
    wrong = SubmitActionCommand[GomokuConfig](
        request_id="wrong-action",
        opportunity_id=view.opportunities[0].opportunity_id,
        expected_state_version=view.state_version,
        action=GomokuConfig(),
    )
    with pytest.raises(ValidationError):
        service.submit_action(connection, black, wrong)
    assert service.read_view(connection, black) == view
    assert service.read_receipt(connection, black, "wrong-action") is None


def test_common_command_with_explicit_types_uses_registered_validation(system):
    service, connection = system
    common = CreateGameCommand[GomokuConfig](
        request_id="create",
        game_type="gomoku",
        ruleset_id="gomoku.freestyle",
        ruleset_version=1,
        initial_seat_id="black",
        config=GomokuConfig(),
    )
    first = service.create_game(connection, "alice", common)
    assert (
        service.create_game(connection, "alice", GomokuCreateGameCommand(request_id="create"))
        == first
    )
    config = service.registry.list_game_types()[0].rulesets[0].config
    assert type(config) is GomokuConfig


def test_concrete_schemas_expose_gameplay_fields_and_keep_common_status():
    schema = GomokuView.model_json_schema()
    assert {"stones", "current_seat_id", "result"} <= set(
        schema["$defs"]["GomokuState"]["properties"]
    )
    assert schema["$defs"]["GameStatus"]["enum"] == ["waiting", "running", "finished", "cancelled"]
    action = GomokuSubmitActionCommand.model_json_schema()["$defs"]["PlaceStoneAction"]
    assert set(action["properties"]) == {"type", "x", "y"}
