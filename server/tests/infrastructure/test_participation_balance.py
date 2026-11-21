import math
from pathlib import Path

import pytest
from support.migrations import load_history

from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.infrastructure.models.registry import load_model_registry
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.social.balance import ParticipationShares
from echo_commons.modules.social.participation import choose_scored
from echo_commons.modules.social.settings import ParticipationSettings


def test_model_score_still_dominates_maximum_participation_correction():
    result = choose_scored(
        {"higher": 0.95, "lower": 0.85, "excluded": 0.2},
        0.8,
        0.1,
        shares={"higher": (0, 1), "lower": (1, 0), "excluded": (1, 0)},
    )
    assert set(result.probabilities) == {"higher", "lower"}
    assert all(0.9 <= factor <= 1.1 for factor in result.corrections.values())
    assert result.probabilities["higher"] > result.probabilities["lower"]
    assert result.base_probabilities["higher"] / result.base_probabilities[
        "lower"
    ] == pytest.approx(math.e)


def test_one_publication_changes_equal_seven_role_weight_slowly():
    scores = {str(i): 0.9 for i in range(7)}
    shares = {str(i): (0.02 / 7, 0.02 if i == 0 else 0) for i in range(7)}
    result = choose_scored(scores, 0.8, 0.1, shares=shares)
    assert result.corrections["0"] == pytest.approx(0.98302, abs=0.0001)
    assert result.corrections["1"] == pytest.approx(1.00286, abs=0.0001)
    assert result.selected in scores
    assert choose_scored({"quiet": 0.3}, 0.8, 0.1).selected is None


def test_real_player_message_does_not_change_participation_shares(tmp_path):
    database = load_history(31, tmp_path / "shares.sqlite3")
    initialize(database)
    models = load_model_registry(Path(__file__).resolve().parents[2] / "config/model-registry.toml")
    configuration = {
        "mode": "remote_willingness",
        "model": models.resolve("light").configuration(),
        "controls": {},
        "protocol": "willingness-json-v1",
        "balance": ParticipationSettings().balance.model_dump(),
    }
    shares = ParticipationShares(
        ParticipationSettings(mode="remote_willingness"), lambda: configuration
    )
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT * FROM messages WHERE sender_kind='player' LIMIT 1"
        ).fetchone()
        message = MessageRepository().get(connection, row["conversation_id"], row["message_id"])
        shares.published(connection, message)
        first = shares.read(connection, message.conversation_id, configuration)
        shares.published(connection, message)
        assert shares.read(connection, message.conversation_id, configuration) == first
        assert first == {}
    initialize(database)
    with database.read() as connection:
        assert shares.read(connection, message.conversation_id, configuration) == first
        new_model = {**configuration, "model": {**configuration["model"], "model": "other-model"}}
        assert shares.read(connection, message.conversation_id, new_model) == {}
