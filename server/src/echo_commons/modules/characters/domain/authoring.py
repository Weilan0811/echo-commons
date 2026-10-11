from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from echo_commons.shared.errors import ConflictError


class AuthoringModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InterviewAnswer(AuthoringModel):
    question_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(max_length=2000)


class PersonaDocuments(AuthoringModel):
    profile: str = Field(min_length=1, max_length=9000)
    voice: str = Field(min_length=1, max_length=4000)
    relational_dynamics: str = Field(min_length=1, max_length=4000)

    @field_validator("profile", "voice", "relational_dynamics")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Content must be nonempty")
        return value


ShortText = Annotated[str, Field(max_length=80)]
DetailText = Annotated[str, Field(max_length=500)]
ListItem = Annotated[str, Field(max_length=200)]


class IntroductionIdentity(AuthoringModel):
    nickname: ShortText = Field(default="", title="称呼")
    age: ShortText = Field(default="", title="年龄")
    gender: ShortText = Field(default="", title="性别")
    occupation: str = Field(default="", max_length=300, title="身份或职业")
    residence: str = Field(default="", max_length=300, title="生活环境")


class IntroductionDailyLife(AuthoringModel):
    hobbies: tuple[ListItem, ...] = Field(default=(), max_length=10, title="爱好")
    likes: tuple[ListItem, ...] = Field(default=(), max_length=10, title="喜欢的事物")
    dislikes: tuple[ListItem, ...] = Field(default=(), max_length=10, title="讨厌的事物")
    habits: tuple[ListItem, ...] = Field(default=(), max_length=10, title="小习惯")
    skills: tuple[ListItem, ...] = Field(default=(), max_length=10, title="特长")

    @field_validator("hobbies", "likes", "dislikes", "habits", "skills")
    @classmethod
    def normalize(cls, values):
        return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


class IntroductionPersonality(AuthoringModel):
    typical_reactions: DetailText = Field(default="", title="常见反应")
    values: DetailText = Field(default="", title="在意的事情")
    stranger_style: DetailText = Field(default="", title="与陌生人的相处")
    close_style: DetailText = Field(default="", title="与熟人的相处")
    boundaries: DetailText = Field(default="", title="明确限制")


class IntroductionSpeech(AuthoringModel):
    examples: tuple[ListItem, ...] = Field(default=(), max_length=3, title="典型台词")
    notes: DetailText = Field(default="", title="语气补充")

    @field_validator("examples")
    @classmethod
    def normalize(cls, values):
        return IntroductionDailyLife.normalize(values)


class IntroductionAppearance(AuthoringModel):
    hair: DetailText = Field(default="", title="发型与发色")
    eyes: DetailText = Field(default="", title="眼睛")
    physique: DetailText = Field(default="", title="体型或身高")
    outfit: DetailText = Field(default="", title="常见衣着")
    distinctive_features: DetailText = Field(default="", title="辨识特征")
    notes: DetailText = Field(default="", title="外貌补充")


class Introduction(AuthoringModel):
    identity: IntroductionIdentity = Field(default_factory=IntroductionIdentity)
    daily_life: IntroductionDailyLife = Field(default_factory=IntroductionDailyLife)
    personality: IntroductionPersonality = Field(default_factory=IntroductionPersonality)
    speech: IntroductionSpeech = Field(default_factory=IntroductionSpeech)
    appearance: IntroductionAppearance = Field(default_factory=IntroductionAppearance)

    def source_fields(self):
        for group_name in type(self).model_fields:
            group = getattr(self, group_name)
            for name, field in type(group).model_fields.items():
                value = getattr(group, name)
                text = "；".join(value) if isinstance(value, tuple) else value.strip()
                if text:
                    yield f"{group_name}.{name}", field.title, text

    def character_count(self):
        return sum(
            sum(len(item) for item in value) if isinstance(value, tuple) else len(value)
            for group in (getattr(self, name) for name in type(self).model_fields)
            for value in (getattr(group, name) for name in type(group).model_fields)
        )

    @model_validator(mode="after")
    def budget(self):
        if self.character_count() > 8000:
            raise ValueError("Introduction exceeds 8000 characters")
        return self


class AuthoringContent(PersonaDocuments):
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=8000)
    story: str = Field(default="", max_length=24000)
    interview: tuple[InterviewAnswer, ...] = Field(default=(), max_length=15)
    avatar_url: str | None = Field(default=None, min_length=1, max_length=2000)
    avatar_asset_id: str | None = Field(default=None, min_length=1)
    introduction: Introduction = Field(default_factory=Introduction)

    @field_validator("display_name", "description")
    @classmethod
    def nonblank_material(cls, value: str) -> str:
        return cls.nonblank(value)

    @model_validator(mode="after")
    def material_budget(self):
        if self.avatar_url and self.avatar_asset_id:
            raise ValueError("Choose one avatar source")
        ids = [item.question_id for item in self.interview]
        if len(set(ids)) != len(ids):
            raise ValueError("Interview question IDs must be unique")
        total = len(self.description) + len(self.story) + self.introduction.character_count()
        total += sum(len(item.question) + len(item.answer) for item in self.interview)
        if total > 40000:
            raise ValueError("Author materials exceed 40000 characters")
        return self


Stage = Literal["basic", "story", "interview"]
StageStatus = Literal["pending", "accepted", "review_required", "unused"]


class InterviewBasis(PersonaDocuments):
    agent_contract: str
    expression_guidance: str
    description: str
    display_name: str
    story: str
    introduction: Introduction = Field(default_factory=Introduction)


class AuthoringWorkflow(AuthoringModel):
    basic: StageStatus = "pending"
    story: StageStatus = "unused"
    interview: StageStatus = "unused"
    documents_review: Literal["review_required", "accepted"] = "review_required"
    interview_basis: InterviewBasis | None = None

    @classmethod
    def initial(cls, content: AuthoringContent, *, copied: bool = False):
        status = "review_required" if copied else "pending"
        return cls(
            story=status if content.story.strip() else "unused",
            interview=status if content.interview else "unused",
        )

    def edited(self, previous: AuthoringContent, current: AuthoringContent):
        values = self.model_dump()
        basic_changed = any(
            getattr(previous, key) != getattr(current, key)
            for key in ("description", "profile", "voice", "relational_dynamics", "introduction")
        )
        story_changed = previous.story != current.story
        interview_changed = previous.interview != current.interview

        def invalidate(stage: Stage, present: bool = True):
            values[stage] = (
                "unused"
                if not present
                else "review_required"
                if getattr(self, stage) in ("accepted", "review_required")
                else "pending"
            )

        if basic_changed:
            invalidate("basic")
        if basic_changed or story_changed:
            invalidate("story", bool(current.story.strip()))
        if basic_changed or story_changed or interview_changed:
            invalidate("interview", bool(current.interview))
        if (
            basic_changed
            or story_changed
            or previous.display_name != current.display_name
            or not current.interview
        ):
            values["interview_basis"] = None
        if (
            basic_changed
            or story_changed
            or interview_changed
            or previous.display_name != current.display_name
        ):
            values["documents_review"] = "review_required"
        return AuthoringWorkflow.model_validate(values)

    def require(self, stage: Stage, content: AuthoringContent):
        if stage != "basic" and self.basic != "accepted":
            raise StageDependencyUnmet("Confirm the basic persona first")
        if stage == "interview":
            if self.story != "accepted" or not content.story.strip():
                raise StageDependencyUnmet("Confirm the story before interview")
            if not 10 <= len(content.interview) <= 15:
                raise InterviewIncomplete("Select 10 to 15 interview questions")

    def confirmed(self, stage: Stage, content: AuthoringContent):
        self.require(stage, content)
        if getattr(self, stage) == "accepted":
            return self
        if stage == "story" and not content.story.strip():
            raise StageDependencyUnmet("Story must be nonempty")
        if stage == "interview" and any(not item.answer.strip() for item in content.interview):
            raise InterviewIncomplete("Complete every selected answer first")
        values = {stage: "accepted"}
        if stage == "basic":
            values["documents_review"] = "accepted"
        return self.model_copy(update=values)

    def require_complete_materials(self, content: AuthoringContent):
        for stage, present in (
            ("basic", True),
            ("story", bool(content.story.strip())),
            ("interview", bool(content.interview)),
        ):
            if present:
                self.require(stage, content)
                if getattr(self, stage) != "accepted":
                    raise StageDependencyUnmet(f"Confirm {stage} before final creation")

    def require_complete(self, content: AuthoringContent):
        self.require_complete_materials(content)
        if self.documents_review != "accepted":
            raise DocumentsReviewRequired("Review the three persona documents")


class CandidateBase(AuthoringModel):
    candidate_id: UUID
    expected_revision: int = Field(ge=1)
    instruction: str = Field(default="", max_length=4000)


class BasicRequest(CandidateBase):
    operation: Literal["basic"]


class StoryRequest(CandidateBase):
    operation: Literal["story"]


class InterviewRequest(CandidateBase):
    operation: Literal["interview"]
    question_ids: tuple[str, ...] = Field(min_length=1, max_length=5)

    @field_validator("question_ids")
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate question IDs")
        return value


class CalibrateRequest(CandidateBase):
    operation: Literal["calibrate"]


CandidateRequest = Annotated[
    BasicRequest | StoryRequest | InterviewRequest | CalibrateRequest,
    Field(discriminator="operation"),
]
REQUEST_ADAPTER = TypeAdapter(CandidateRequest)


class BasicOutput(PersonaDocuments):
    operation: Literal["basic"]
    description: str = Field(min_length=1, max_length=8000)
    changes: tuple[str, ...] = Field(max_length=32)


class StoryOutput(AuthoringModel):
    operation: Literal["story"]
    story: str = Field(min_length=1, max_length=24000)
    changes: tuple[str, ...] = Field(max_length=32)

    @field_validator("story")
    @classmethod
    def nonblank(cls, value):
        return PersonaDocuments.nonblank(value)


class InterviewResponse(AuthoringModel):
    question_id: str = Field(min_length=1, max_length=80)
    answer: str = Field(min_length=1, max_length=2000)


class InterviewOutput(AuthoringModel):
    operation: Literal["interview"]
    answers: tuple[InterviewResponse, ...] = Field(min_length=1, max_length=5)
    new_background_suggestions: tuple[str, ...] = Field(max_length=15)


class CalibrationChange(AuthoringModel):
    document: Literal["profile", "voice", "relational_dynamics"]
    explanation: str = Field(min_length=1, max_length=2000)
    source_refs: tuple[str, ...] = Field(min_length=1, max_length=32)


class CalibrationConflict(AuthoringModel):
    explanation: str = Field(min_length=1, max_length=2000)
    source_refs: tuple[str, ...] = Field(min_length=1, max_length=32)


class CalibrateOutput(PersonaDocuments):
    operation: Literal["calibrate"]
    changes: tuple[CalibrationChange, ...] = Field(max_length=32)
    conflicts: tuple[CalibrationConflict, ...] = Field(max_length=32)


CandidateOutput = Annotated[
    BasicOutput | StoryOutput | InterviewOutput | CalibrateOutput, Field(discriminator="operation")
]
OUTPUT_ADAPTER = TypeAdapter(CandidateOutput)


def merge_candidate(content: AuthoringContent, output: CandidateOutput) -> AuthoringContent:
    if output.operation == "basic":
        values = output.model_dump(
            include={"description", "profile", "voice", "relational_dynamics"}
        )
    elif output.operation == "story":
        values = {"story": output.story}
    elif output.operation == "interview":
        answers = {item.question_id: item.answer for item in output.answers}
        if len(answers) != len(output.answers) or not set(answers) <= {
            item.question_id for item in content.interview
        }:
            raise ValueError("Interview output must use unique selected question IDs")
        if any(not answer.strip() for answer in answers.values()):
            raise ValueError("Interview answer must be nonempty")
        values = {
            "interview": tuple(
                item.model_copy(update={"answer": answers.get(item.question_id, item.answer)})
                for item in content.interview
            )
        }
    else:
        values = output.model_dump(include={"profile", "voice", "relational_dynamics"})
    return AuthoringContent.model_validate(content.model_dump() | values)


class DraftRevisionConflict(ConflictError):
    code = "draft_revision_conflict"


class BlueprintImmutable(ConflictError):
    code = "blueprint_immutable"


class CandidateStale(ConflictError):
    code = "candidate_stale"


class StageDependencyUnmet(ConflictError):
    code = "stage_dependency_unmet"


class InterviewIncomplete(ConflictError):
    code = "interview_incomplete"


class DocumentsReviewRequired(ConflictError):
    code = "documents_review_required"


class CalibrationConflictError(ConflictError):
    code = "calibration_conflict"


class InterviewSelectionInvalid(ValueError):
    code = "authoring_input_invalid"
