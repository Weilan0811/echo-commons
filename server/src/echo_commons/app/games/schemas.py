from typing import Annotated, Literal

from echo_games.public import (
    CreateGameCommand,
    GomokuOperationReceipt,
    GomokuSummary,
    Participation,
    SubmitActionCommand,
)
from pydantic import BaseModel, ConfigDict, Field

from echo_commons.app.http import RequestModel
from echo_commons.modules.activities.contracts import CharacterParticipationReason
from echo_commons.modules.communities.contracts import (
    GameSessionOperationKind,
    GameSessionOperationResult,
)
from echo_commons.modules.communities.game_query import GameCapabilities, GameSessionView
from echo_commons.modules.conversations.api.schemas import ConversationView
from echo_commons.modules.conversations.domain.conversation import Membership


class UnvalidatedPayload(BaseModel):
    """
    宿主不解释的玩法数据。

    输入的配置与动作、目录里的规则配置都由它承载。输入侧只要求是键值对象，
    具体字段由所选玩法的命令模型校验，玩法不接受的取值返回 `invalid_command`。
    """

    model_config = ConfigDict(extra="allow")


class RulesetResponse(BaseModel):
    ruleset_id: str
    ruleset_version: int
    display_name: str
    min_players: int
    max_players: int
    config: UnvalidatedPayload


class GameTypeResponse(BaseModel):
    game_type: str
    display_name: str
    rulesets: tuple[RulesetResponse, ...]


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


class CreateGameRequest(CreateGameCommand[UnvalidatedPayload]):
    player_id: str = Field(min_length=1, pattern=r"\S")
    community_id: str = Field(min_length=1, pattern=r"\S")
    config: UnvalidatedPayload = Field(default_factory=UnvalidatedPayload)


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


class SubmitGameActionRequest(SubmitActionCommand[UnvalidatedPayload]):
    player_id: str = Field(min_length=1, pattern=r"\S")
