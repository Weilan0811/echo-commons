from functools import partial
from uuid import uuid4

from echo_commons.modules.conversations.domain.message import PlayerMessage
from support.games import create, move, operation
from support.http import create_group


def activity_game(client, *, memory_mode="simple"):
    create_group(client, memory_mode=memory_mode)
    created, _ = create(client)
    game_id = created["game_id"]
    operation(
        client,
        game_id,
        "participants",
        seat_id="white",
        participant={"kind": "character", "character_id": "first"},
    )
    operation(client, game_id, "start")
    move(client, game_id, "alice", 7, 7)
    return game_id


def prepare(client, game_id, *, kind="reply", character="first", input_id=None):
    method = getattr(client.app.state.application.activity_context, f"prepare_{kind}")
    return client.portal.call(
        partial(method, "community", character, game_id, input_id=input_id or uuid4().hex)
    )


def message(client, game_id, text, **options):
    app = client.app.state.application
    with app.database.read() as connection:
        row = connection.execute(
            "SELECT conversation_id FROM community_games WHERE game_id=?", (game_id,)
        ).fetchone()
    return app.intake.send(
        "community", row[0], PlayerMessage("alice", uuid4().hex, text, **options)
    )
