from uuid import uuid4

from echo_games.public import (
    GomokuCreateGameCommand,
    GomokuSubmitActionCommand,
    PlaceStoneAction,
    StartGameCommand,
)

from echo_commons.modules.communities.contracts import (
    CreateGameSessionCommand,
    JoinGameSessionCommand,
)
from echo_commons.shared.actors import ActorRef

ALICE = ActorRef("player", "alice")
CHARACTER = ActorRef("character", "first")


def create_character_black(app):
    created = app.game_participation.create_game(
        ALICE,
        CreateGameSessionCommand(
            community_id="community",
            game=GomokuCreateGameCommand(request_id=uuid4().hex, initial_seat_id="white"),
        ),
    )
    app.game_participation.join_game(
        ALICE,
        JoinGameSessionCommand(
            game_id=created.game_id,
            request_id=uuid4().hex,
            expected_state_version=1,
            seat_id="black",
            participant=CHARACTER,
        ),
    )
    app.game_participation.start_game(
        ALICE,
        StartGameCommand(game_id=created.game_id, request_id=uuid4().hex, expected_state_version=2),
    )
    return created.game_id


def play_in(app, connection, game_id, actor, action):
    context = app.game_queries.participant_context(connection, "community", actor, game_id)
    view = app.games.read_view(connection, context.access)
    command = GomokuSubmitActionCommand(
        request_id=uuid4().hex,
        opportunity_id=view.opportunities[0].opportunity_id,
        expected_state_version=view.state_version,
        action=action,
    )
    return app.games.submit_action(connection, context.access, command)


def fill_draw(app, game_id, count):
    black, white = [], []
    for y in range(15):
        for x in range(15):
            (black if (x // 2 + y) % 2 == 0 else white).append(PlaceStoneAction(x=x, y=y))
    with app.database.transaction() as connection:
        for index in range(count):
            play_in(
                app,
                connection,
                game_id,
                CHARACTER if index % 2 == 0 else ALICE,
                black[index // 2] if index % 2 == 0 else white[index // 2],
            )


def task_row(app, task_id):
    with app.database.read() as connection:
        return dict(app.activity_queue.repository.get(connection, task_id))
