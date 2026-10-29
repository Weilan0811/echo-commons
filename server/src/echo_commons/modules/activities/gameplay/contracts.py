from typing import Generic, Protocol, TypeVar

from echo_games.public import ActionOpportunity, GameView
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SerializeAsAny

ActionT = TypeVar("ActionT", bound=BaseModel)


class AnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleFact(AnalysisModel):
    code: str
    description: str
    details: dict[str, JsonValue] = Field(default_factory=dict)


class SearchEstimate(AnalysisModel, Generic[ActionT]):
    source: str
    scale: str
    value: float
    continuation: tuple[ActionT, ...]
    details: dict[str, JsonValue] = Field(default_factory=dict)


class ActionCandidate(AnalysisModel, Generic[ActionT]):
    candidate_id: str
    action: ActionT
    origins: tuple[str, ...]
    facts: tuple[RuleFact, ...]
    estimates: tuple[SearchEstimate[ActionT], ...] = ()


class AnalysisRun(AnalysisModel):
    analyzer: str
    version: str
    resources: dict[str, JsonValue]


class GameplayAnalysis(AnalysisModel, Generic[ActionT]):
    schema_version: int = 1
    game_id: str
    game_type: str
    ruleset_id: str
    ruleset_version: int
    state_version: int
    participation_id: str
    opportunity_id: str
    legal_action_count: int
    choice_required: bool
    candidates: tuple[ActionCandidate[ActionT], ...]
    recommended_candidate_id: str
    runs: tuple[AnalysisRun, ...]
    failures: tuple[str, ...] = ()


class AnalysisRequest(AnalysisModel):
    view: SerializeAsAny[GameView]
    opportunity: SerializeAsAny[ActionOpportunity]
    suggested_actions: tuple[SerializeAsAny[BaseModel], ...] = ()


class GameplayAnalysisError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code, self.retryable = code, retryable
        self.failures: tuple[str, ...] = ()


class GameplayAnalyzer(Protocol):
    game_type: str
    ruleset_id: str
    ruleset_version: int

    async def analyze(self, request: AnalysisRequest) -> GameplayAnalysis: ...
