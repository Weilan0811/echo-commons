from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from echo_games.public import ActionOpportunity, GameEventPayload, GameViewPayload
from pydantic import (
    BaseModel,
    Field,
    TypeAdapter,
    field_validator,
    model_serializer,
    model_validator,
)

from echo_commons.agents.contracts.context import (
    ContextSnapshot,
    ParticipantIdentity,
    SnapshotModel,
)
from echo_commons.agents.contracts.input import (
    ActorScope,
    InvocationInput,
    SourceVersion,
    ToolReadPolicy,
)
from echo_commons.agents.contracts.output import CheckedCharacterExpression
from echo_commons.agents.contracts.refs import OutputContractRef
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


class ActivityResponseProgress(SnapshotModel):
    source_id: str
    social_turn_id: str
    message_ids: tuple[str, ...]
    status: str
    current: bool
    result_id: str | None = None


class ActivityParticipant(ParticipantIdentity):
    participation_id: str
    seat_id: str
    joined_at_utc: datetime
    left_at_utc: datetime | None = None


class ActivitySessionContext(SnapshotModel):
    game_id: str
    game_type: str
    ruleset_id: str
    ruleset_version: int
    rules: str
    self_participation_id: str
    participants: tuple[ActivityParticipant, ...]
    result: dict | None = None

    @property
    def winners(self) -> tuple[ActivityParticipant, ...]:
        result = self.result or {}
        seats = result.get("winner_seat_ids", ())
        if result.get("winner_seat_id") is not None:
            seats = (result["winner_seat_id"],)
        return tuple(p for p in self.participants if p.seat_id in seats and p.left_at_utc is None)


class ActivityEvidence(SnapshotModel):
    session_context: ActivitySessionContext | None = None
    conversation: ContextSnapshot
    game: ActivityObservationSnapshot
    working_memory: WorkingMemory
    private_thoughts: tuple[ActivityPrivateThought, ...] = ()
    responses: tuple[ActivityResponseProgress, ...] = ()
    reaction_event_ids: tuple[str, ...] = ()
    expression_allowed: bool = True

    @model_serializer(mode="wrap")
    def serialize_frozen(self, handler):
        result = handler(self)
        for name in (
            "session_context",
            "private_thoughts",
            "responses",
            "reaction_event_ids",
            "expression_allowed",
        ):
            if name not in self.model_fields_set:
                result.pop(name, None)
        return result


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
    prompt_layout_version: Literal[1, 2] = 2
    scope: ActivityScope
    material: ActivityMaterial

    @property
    def read_policy(self) -> ToolReadPolicy:
        return self.material.conversation.read_policy

    @model_validator(mode="after")
    def consistent_material(self):
        common = self.material.conversation
        session = self.material.session_context
        if session is not None and (
            session.game_id != self.scope.game_id
            or session.self_participation_id != self.scope.participation_id
            or not any(
                p.participation_id == self.scope.participation_id
                and p.seat_id == self.scope.seat_id
                and p.actor.actor_id == self.scope.character_id
                and p.actor.kind == "character"
                and p.is_self
                for p in session.participants
            )
        ):
            raise ValueError("Activity session identity does not match its participation")
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


class ExpressionOrigin(SnapshotModel):
    input_id: str
    prepared_at_utc: datetime
    state_version: int
    message_upper_sequence: int
    message_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    source_versions: tuple[SourceVersion, ...]
    decision: dict


class ActivityExpressionInput(ActivityInput):
    prompt_layout_version: Literal[1, 2, 3] = 3
    phase: Literal["independent", "before_action"] = "independent"
    origin: ExpressionOrigin | None = None
    kind: Literal["expression"] = "expression"
    origin_input_id: str
    receipt: dict | None
    current_observation: dict
    receipt_event_ids: tuple[str, ...] = ()

    @model_serializer(mode="wrap")
    def serialize_expression(self, handler):
        result = handler(self)
        if "origin" not in self.model_fields_set:
            result.pop("origin", None)
        if "phase" not in self.model_fields_set:
            result.pop("phase", None)
        return result


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


def turn_contract(game_type: str) -> OutputContractRef:
    return OutputContractRef(kind=f"activity_{game_type}_turn", version="v1")


def selection_contract(game_type: str) -> OutputContractRef:
    return OutputContractRef(kind=f"activity_{game_type}_selection", version="v1")


ACTIVITY_REPLY_CONTRACT = OutputContractRef(kind="activity_reply", version="v1")
ACTIVITY_REPLY_SELECTION_CONTRACT = OutputContractRef(kind="activity_reply_selection", version="v1")
LEGACY_ACTIVITY_EXPRESSION_CONTRACT = OutputContractRef(kind="activity_expression", version="v1")
ACTIVITY_EXPRESSION_CONTRACT = OutputContractRef(kind="activity_expression", version="v2")


class LegacyActivityExpressionProposal(SnapshotModel):
    expression: CheckedCharacterExpression | None = None
    intents: tuple[IntentProposal, ...] | None = None
    comments_on_action: bool = False


class ActivityExpressionProposal(SnapshotModel):
    expression: CheckedCharacterExpression | None = None
    comments_on_action: bool = False


class TurnExpressionStage(SnapshotModel):
    schema_version: Literal[1] = 1
    timing: Literal["with_action"] = "with_action"
    input: ActivityExpressionInput | None = None
    invocation: dict | None = None
    run: dict | None = None
    proposal: ActivityExpressionProposal | None = None


class ExpressionGoal(SnapshotModel):
    purpose: str = Field(min_length=1, max_length=500)
    evidence_refs: tuple[str, ...]


class ActivityTurnProposal(SnapshotModel, Generic[ActionT]):
    action: ActionT
    understanding: ActivityUnderstanding
    intents: tuple[IntentProposal, ...]
    expression: CheckedCharacterExpression | None = None
    comments_on_action: bool = False


class ActivitySelection(SnapshotModel, Generic[ActionT]):
    action: ActionT
    retained_intent_ids: tuple[str, ...]
    expression_needed: bool
    expression_goal: ExpressionGoal | None = None


class ActivityReplyProposal(SnapshotModel):
    understanding: ActivityUnderstanding
    intents: tuple[IntentProposal, ...] = ()
    expression: CheckedCharacterExpression | None = None


class ActivityReplySelection(SnapshotModel):
    retained_intent_ids: tuple[str, ...]
    expression_needed: bool
    expression_goal: ExpressionGoal | None = None


class ActivityReactionProposal(SnapshotModel):
    understanding: ActivityUnderstanding
    expression: CheckedCharacterExpression | None = None


class DecisionTurn(SnapshotModel):
    kind: Literal["turn"] = "turn"
    opportunity_id: str
    action: dict


class DecisionReply(SnapshotModel):
    kind: Literal["reply"] = "reply"


class SilentDecision(SnapshotModel):
    kind: Literal["silent"] = "silent"


class ComposeDecision(SnapshotModel):
    kind: Literal["compose"] = "compose"
    goal: ExpressionGoal


class ReadyDecision(SnapshotModel):
    kind: Literal["ready"] = "ready"
    expression: CheckedCharacterExpression
    comments_on_action: bool


class ActivityDecision(SnapshotModel):
    schema_version: Literal[1] = 1
    decision_id: str
    input_id: str | None
    mode: Literal["automatic", "decision", "ordinary", "decision_then_ordinary"]
    scope: ActivityScope
    state_version: int
    working_memory_version: int | None
    subject: Annotated[DecisionTurn | DecisionReply, Field(discriminator="kind")]
    speech: Annotated[SilentDecision | ComposeDecision | ReadyDecision, Field(discriminator="kind")]
    intents: tuple[IntentProposal, ...] | None
    thought: str | None
    source_versions: tuple[SourceVersion, ...]
    handoff_reasons: tuple[str, ...] = ()
