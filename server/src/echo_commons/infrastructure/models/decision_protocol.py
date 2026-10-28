from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue

from echo_commons.agents.contracts.run import UsageSummary

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class DecisionControls(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    think_mode: Literal["never", "auto", "always"] = "never"
    gate: Probability = 0.6
    think_budget: int = Field(default=4096, ge=1)
    mix: Probability = 0.75
    allow_none: bool = False
    none_check: bool = True
    return_details: bool = False
    return_thought: bool = False
    thought_generation: Literal["auto", "stream", "chunked"] = "auto"


class DecisionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    enabled: bool = False
    profile: str = Field(default="decision", min_length=1)
    timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    input_max_chars: int = Field(default=32000, ge=1)
    controls: DecisionControls = Field(default_factory=DecisionControls)


class ChoiceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["choice"] = "choice"
    instructions: str = Field(min_length=1)
    criteria: dict[str, str | None] = Field(min_length=1)
    allow_none: bool | None = None


class NoulQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["noul"] = "noul"
    instructions: str = Field(min_length=1)


class ScoreQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["score"] = "score"
    instructions: str = Field(min_length=1)
    criteria: tuple[str, ...] = Field(min_length=2, max_length=10)


Question = Annotated[ChoiceQuestion | NoulQuestion | ScoreQuestion, Field(discriminator="type")]


class DecisionRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str
    model_vendor: str
    model: str
    base_url: str
    credential_ref: str | None
    access_route: str
    request_timeout_seconds: float = Field(gt=0)
    retry_backoff_seconds: float = Field(ge=0)
    input_max_chars: int = Field(ge=1)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: UUID
    trace_id: UUID
    agent_id: str
    attempt: int = Field(default=1, ge=1)
    step_index: int = Field(default=1, ge=1)
    model_profile: str | None = None
    model_entry_id: str | None = None
    route: DecisionRoute | None = None
    state: JsonValue
    questions: dict[str, Question] = Field(min_length=1)
    controls: DecisionControls | None = None
    max_provider_retries: int | None = Field(default=None, ge=0)
    deadline_utc: AwareDatetime | None = None

    def payload(self) -> dict[str, object]:
        if self.controls is None:
            raise ValueError("Decision controls must be prepared before sending")
        return {
            "state": self.state,
            "questions": {
                key: question.model_dump(mode="json", exclude_none=True)
                for key, question in self.questions.items()
            },
            **self.controls.model_dump(),
        }


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["choice"]
    choice: str | None
    confidence: Probability
    probabilities: dict[str, Probability] = Field(min_length=1)
    none_probability: Probability | None = None
    details: dict[str, JsonValue] | None = None


class NoulAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["noul"]
    noul: Probability
    details: dict[str, JsonValue] | None = None


class ScoreAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["score"]
    score: float = Field(allow_inf_nan=False)
    confidence: Probability
    legend: dict[str, str]
    probabilities: dict[str, Probability] = Field(min_length=2, max_length=10)
    details: dict[str, JsonValue] | None = None


Answer = Annotated[ChoiceAnswer | NoulAnswer | ScoreAnswer, Field(discriminator="type")]


class DecisionUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answers: dict[str, Answer]
    model: str = Field(min_length=1)
    usage: DecisionUsage | None = None
    timing_ms: dict[str, float] | None = None
    model_entry_id: str
    latency_ms: int = Field(ge=0)
    provider_attempt: int = Field(ge=1)
    request_id: str | None = None

    @property
    def usage_summary(self) -> UsageSummary:
        incoming = self.usage.input_tokens if self.usage else None
        outgoing = self.usage.output_tokens if self.usage else None
        return UsageSummary(
            model_request_count=1,
            input_tokens=incoming or 0,
            output_tokens=outgoing or 0,
            total_tokens=(incoming or 0) + (outgoing or 0),
        )

    def validate_answers(self, request: DecisionRequest) -> None:
        if self.answers.keys() != request.questions.keys():
            raise ValueError("Decision answers do not match requested questions")
        for key, question in request.questions.items():
            answer = self.answers[key]
            if answer.type != question.type:
                raise ValueError("Decision answer type does not match question")
            if isinstance(question, ChoiceQuestion):
                if answer.probabilities.keys() != question.criteria.keys():
                    raise ValueError("Decision options do not match requested criteria")
                allow_none = question.allow_none
                if allow_none is None:
                    allow_none = request.controls.allow_none
                if answer.choice not in question.criteria and not (
                    answer.choice is None and allow_none
                ):
                    raise ValueError("Decision selected an unknown option")
            elif isinstance(question, ScoreQuestion):
                expected = {str(i): value for i, value in enumerate(question.criteria)}
                if answer.legend != expected or answer.probabilities.keys() != expected.keys():
                    raise ValueError("Decision score levels do not match requested criteria")
                if not 0 <= answer.score <= len(question.criteria) - 1:
                    raise ValueError("Decision score is outside requested levels")
            if (
                isinstance(answer, ChoiceAnswer | ScoreAnswer)
                and abs(sum(answer.probabilities.values()) - 1) > 0.001
            ):
                raise ValueError("Decision probabilities must sum to one")
