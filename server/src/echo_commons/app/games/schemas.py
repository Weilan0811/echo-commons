from typing import Annotated, Literal

from echo_games.public import (
    GomokuConfig,
    GomokuCreateGameCommand,
    GomokuOperationReceipt,
    GomokuSubmitActionCommand,
    GomokuSummary,
    Participation,
    RulesetView,
)
from pydantic import BaseModel, Field

from echo_commons.app.http import RequestModel
from echo_commons.modules.activities.contracts import CharacterParticipationReason
from echo_commons.modules.communities.contracts import (
    GameSessionOperationKind,
    GameSessionOperationResult,
)
from echo_commons.modules.communities.game_query import GameCapabilities, GameSessionView
from echo_commons.modules.conversations.api.schemas import ConversationView
from echo_commons.modules.conversations.domain.conversation import Membership


class GameTypeResponse(BaseModel):
    game_type: Literal["gomoku"]
    display_name: str
    rulesets: tuple[RulesetView[GomokuConfig], ...]


class GameTypesResponse(BaseModel):
    items: tuple[GameTypeResponse, ...]


class GameSessionResponse(BaseModel):
    community_id: str
    game: GomokuSummary
    conversation: ConversationView
    self_participations: tuple[Participation, ...]
    self_participation_id: str | None
    capabilities: GameCapabilities

    @classmethod
    def from_session(cls, session: GameSessionView):
        return cls(
            community_id=session.community_id,
            game=session.game,
            conversation=ConversationView.model_validate(
                session.conversation, from_attributes=True
            ),
            self_participations=session.self_participations,
            self_participation_id=session.self_participation_id,
            capabilities=session.capabilities,
        )


class GameOperationResponse(BaseModel):
    community_id: str
    game_id: str
    operation: GameSessionOperationKind
    conversation: ConversationView
    memberships: tuple[Membership, ...]
    game_receipt: GomokuOperationReceipt | None

    @classmethod
    def from_operation(cls, result: GameSessionOperationResult):
        return cls(
            community_id=result.community_id,
            game_id=result.game_id,
            operation=result.operation,
            conversation=ConversationView.model_validate(result.conversation, from_attributes=True),
            memberships=result.memberships,
            game_receipt=result.game_receipt,
        )


class CreateGameRequest(GomokuCreateGameCommand):
    player_id: str = Field(min_length=1, pattern=r"\S")
    community_id: str = Field(min_length=1, pattern=r"\S")


class GameOperationRequest(RequestModel):
    player_id: str = Field(min_length=1, pattern=r"\S")
    request_id: str = Field(min_length=1, pattern=r"\S")
    expected_state_version: int = Field(ge=1)


class PlayerParticipant(RequestModel):
    kind: Literal["player"]


class CharacterParticipant(RequestModel):
    kind: Literal["character"]
    character_id: str = Field(min_length=1, pattern=r"\S")


JoinParticipant = Annotated[PlayerParticipant | CharacterParticipant, Field(discriminator="kind")]


class GameCharacterCandidate(BaseModel):
    character_id: str
    eligible: bool
    reason: CharacterParticipationReason | Literal["already_seated"] | None


class JoinGameRequest(GameOperationRequest):
    seat_id: str = Field(min_length=1, pattern=r"\S")
    participant: JoinParticipant


class LeaveGameRequest(GameOperationRequest):
    participation_id: str = Field(min_length=1, pattern=r"\S")


class ResignGameRequest(GameOperationRequest):
    participation_id: str = Field(min_length=1, pattern=r"\S")


class CancelGameRequest(GameOperationRequest):
    reason: str = Field(min_length=1, pattern=r"\S")


class EndGameRequest(GameOperationRequest):
    expected_conversation_version: int = Field(ge=1)


class SubmitGameActionRequest(GomokuSubmitActionCommand):
    player_id: str = Field(min_length=1, pattern=r"\S")
