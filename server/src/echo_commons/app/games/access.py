from typing import Annotated

from fastapi import Depends, Query

from echo_commons.shared.actors import ActorRef


def game_requester(player_id: Annotated[str, Query(min_length=1, pattern=r"\S")]) -> ActorRef:
    return ActorRef("player", player_id)


GameRequester = Annotated[ActorRef, Depends(game_requester)]
