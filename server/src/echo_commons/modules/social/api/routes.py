from typing import Annotated

from fastapi import APIRouter, Depends, Query

from echo_commons.app.composition import Application
from echo_commons.app.http import application_for
from echo_commons.modules.social.api.schemas import ParticipationView, TurnView

router = APIRouter(prefix="/api", tags=["social"])
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.get("/conversations/{conversation_id}/turns", response_model=list[TurnView])
def read_turns(
    conversation_id: str,
    player_id: str,
    application: ApplicationDependency,
    limit: int = Query(default=50, ge=1, le=200),
):
    community = application.conversations.community_id(conversation_id)
    return [
        TurnView(
            social_turn_id=item.turn.social_turn_id,
            conversation_id=conversation_id,
            status=item.turn.status,
            created_at_utc=item.turn.created_at_utc,
            completed_at_utc=item.turn.completed_at_utc,
            participation=tuple(
                ParticipationView.model_validate(decision, from_attributes=True)
                for decision in item.participation
            ),
        )
        for item in application.turns.read(community, conversation_id, player_id, limit=limit)
    ]
