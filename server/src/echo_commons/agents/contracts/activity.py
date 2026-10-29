from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from echo_games.public import ActionOpportunity, GameEventPayload, GameViewPayload
from pydantic import BaseModel, Field, TypeAdapter, field_validator, model_validator

from echo_commons.agents.contracts.context import ContextSnapshot, SnapshotModel
from echo_commons.agents.contracts.input import ActorScope, InvocationInput, ToolReadPolicy
from echo_commons.modules.activities.gameplay.contracts import GameplayAnalysis

ActionT = TypeVar("ActionT", bound=BaseModel)


class ActivityScope(ActorScope):
    game_id: str
    participation_id: str
    seat_id: str
    conversation_id: str
    membership_id: str


class IntentProposal(SnapshotModel):
    content: str = Field(min_length=1, max_length=2000)
    message_ids: tuple[str, ...] = ()


class WorkingIntent(IntentProposal):
    intent_id: str
    source_input_id: str


class WorkingMemory(SnapshotModel):
    version: int = Field(default=0, ge=0)
    intents: tuple[WorkingIntent, ...] = ()
    last_input_id: str | None = None


class PersonaText(SnapshotModel):
    profile: str
    voice: str
    relational_dynamics: str


class PersonaProjection(PersonaText):
    source_version: str
    mode: Literal["direct", "model"]


class ActivityObservationSnapshot(SnapshotModel):
    rules: str
    game_type: str
    ruleset_id: str
    ruleset_version: int
    status: str
    state_version: int
    occurred_at_utc: datetime
    view: GameViewPayload | None
    events: tuple[GameEventPayload, ...]
    after_event_sequence: int = Field(ge=0)
    through_event_sequence: int = Field(ge=0)
    has_more_events: bool
    after_message_sequence: int = Field(ge=0)
    through_message_sequence: int = Field(ge=0)
    progress_version: int = Field(ge=0)


class ActivityPrivateThought(SnapshotModel):
    input_id: str
    occurred_at_utc: datetime
    thought: str


class ActivityEvidence(SnapshotModel):
    conversation: ContextSnapshot
    game: ActivityObservationSnapshot
    working_memory: WorkingMemory
    private_thoughts: tuple[ActivityPrivateThought, ...] = ()


class ActivityMaterial(ActivityEvidence):
    decision_persona: PersonaProjection


class ActivityPreparation(SnapshotModel):
    schema_version: Literal[1] = 1
    input_id: str
    scope: ActivityScope
    evidence: ActivityEvidence


class TurnPreparation(ActivityPreparation):
    kind: Literal["turn"] = "turn"
    opportunity_id: str
    suggested_actions: tuple[dict, ...] = ()


class ReplyPreparation(ActivityPreparation):
    kind: Literal["reply"] = "reply"


class ReactionPreparation(ActivityPreparation):
    kind: Literal["reaction"] = "reaction"


PREPARATION_ADAPTER = TypeAdapter(
    Annotated[TurnPreparation | ReplyPreparation | ReactionPreparation, Field(discriminator="kind")]
)


class ActivityInput(InvocationInput):
    schema_version: Literal[1] = 1
    prompt_layout_version: Literal[1] = 1
    scope: ActivityScope
    material: ActivityMaterial

    @property
    def read_policy(self) -> ToolReadPolicy:
        return self.material.conversation.read_policy

    @model_validator(mode="after")
    def consistent_material(self):
        common = self.material.conversation
        if (
            common.scope.community_id,
            common.scope.character_id,
            common.scope.conversation_id,
            common.scope.membership_id,
        ) != (
            self.scope.community_id,
            self.scope.character_id,
            self.scope.conversation_id,
            self.scope.membership_id,
        ):
            raise ValueError("Activity material belongs to a different character or membership")
        if self.material.game.view is not None:
            view = self.material.game.view
            if (view.game_id, view.viewer_participation_id, view.viewer_seat_id) != (
                self.scope.game_id,
                self.scope.participation_id,
                self.scope.seat_id,
            ):
                raise ValueError("Activity game view belongs to a different participation")
        return self


class ActivityTurnInput(ActivityInput, Generic[ActionT]):
    kind: Literal["turn"] = "turn"
    opportunity: ActionOpportunity[ActionT]
    analysis: GameplayAnalysis[ActionT]

    @model_validator(mode="after")
    def consistent_action(self):
        if (
            self.analysis.game_id,
            self.analysis.state_version,
            self.analysis.participation_id,
            self.analysis.opportunity_id,
        ) != (
            self.scope.game_id,
            self.material.game.state_version,
            self.scope.participation_id,
            self.opportunity.opportunity_id,
        ):
            raise ValueError("Activity analysis does not match the frozen opportunity")
        if self.opportunity.expected_state_version != self.material.game.state_version:
            raise ValueError("Activity opportunity does not match the frozen game version")
        return self


class ActivityReplyInput(ActivityInput):
    kind: Literal["reply"] = "reply"


class ActivityReactionInput(ActivityInput):
    kind: Literal["reaction"] = "reaction"


class MessageUnderstanding(SnapshotModel):
    message_id: str
    interpretation: str = Field(min_length=1)

    @field_validator("interpretation")
    @classmethod
    def meaningful(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message understanding must contain meaningful text")
        return value.strip()


class ActivityUnderstanding(SnapshotModel):
    messages: tuple[MessageUnderstanding, ...]
    event_ids: tuple[str, ...]
    thought: str = Field(default="", max_length=1000)
