from datetime import datetime

from pydantic import BaseModel

from echo_commons.modules.social.domain import ParticipationStatus, TurnStatus


class ParticipationView(BaseModel):
    character_id: str
    reason_code: str
    selection_order: int | None
    status: ParticipationStatus
    outcome: str | None


class TurnView(BaseModel):
    social_turn_id: str
    conversation_id: str
    status: TurnStatus
    created_at_utc: datetime
    completed_at_utc: datetime | None
    participation: tuple[ParticipationView, ...]
