from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from echo_commons.app.http import ErrorBody, RequestModel
from echo_commons.modules.characters.domain.authoring import (
    REQUEST_ADAPTER,
    AuthoringContent,
    AuthoringWorkflow,
    BasicRequest,
    CalibrateRequest,
    CandidateOutput,
    InterviewAnswer,
    InterviewRequest,
    StoryRequest,
)
from echo_commons.modules.characters.templates.authoring import default_content


class CreateDraft(RequestModel):
    player_id: str = Field(min_length=1)
    draft_id: UUID
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=8000)
    story: str = Field(default="", max_length=24000)
    interview: tuple[InterviewAnswer, ...] = Field(default=(), max_length=15)
    profile: str | None = Field(default=None, min_length=1, max_length=8000)
    voice: str | None = Field(default=None, min_length=1, max_length=4000)
    relational_dynamics: str | None = Field(default=None, min_length=1, max_length=4000)
    avatar_url: str | None = Field(default=None, min_length=1, max_length=2000)

    def content(self) -> AuthoringContent:
        if self.profile is not None:
            # 明确正文时只为缺少的风格字段提供默认值，原始长材料仍完整保存。
            base = default_content(self.display_name, self.description)
            return AuthoringContent.model_validate(
                base.model_dump()
                | {
                    "story": self.story,
                    "interview": self.interview,
                    "profile": self.profile,
                    "voice": self.voice if self.voice is not None else base.voice,
                    "relational_dynamics": (
                        self.relational_dynamics
                        if self.relational_dynamics is not None
                        else base.relational_dynamics
                    ),
                    "avatar_url": self.avatar_url,
                }
            )
        base = default_content(
            self.display_name,
            self.description,
            self.story,
            self.interview,
            self.avatar_url,
        )
        return AuthoringContent.model_validate(
            base.model_dump()
            | {
                "voice": self.voice if self.voice is not None else base.voice,
                "relational_dynamics": (
                    self.relational_dynamics
                    if self.relational_dynamics is not None
                    else base.relational_dynamics
                ),
            }
        )


class UpdateDraft(RequestModel):
    player_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    content: AuthoringContent


class ConfirmDraft(RequestModel):
    player_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    acknowledge_fixed_background: Literal[True]


class CopyDraft(RequestModel):
    player_id: str = Field(min_length=1)
    draft_id: UUID


class CandidatePlayer:
    def request(self):
        return REQUEST_ADAPTER.validate_python(self.model_dump(exclude={"player_id"}))


class GenerateBasic(BasicRequest, CandidatePlayer):
    player_id: str = Field(min_length=1)


class GenerateStory(StoryRequest, CandidatePlayer):
    player_id: str = Field(min_length=1)


class GenerateInterview(InterviewRequest, CandidatePlayer):
    player_id: str = Field(min_length=1)


class GenerateCalibrate(CalibrateRequest, CandidatePlayer):
    player_id: str = Field(min_length=1)


GenerateCandidate = Annotated[
    GenerateBasic | GenerateStory | GenerateInterview | GenerateCalibrate,
    Field(discriminator="operation"),
]


class DraftAction(RequestModel):
    player_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)


class ConfirmDocuments(DraftAction):
    acknowledge_documents_match: Literal[True]


class DraftView(BaseModel):
    draft_id: str
    owner_player_id: str
    status: Literal["draft", "confirmed"]
    revision: int
    content: AuthoringContent
    workflow: AuthoringWorkflow
    confirmed_blueprint_id: str | None
    accepted_candidate_id: str | None
    material_processing: Literal["stored_only"]
    created_at_utc: datetime
    updated_at_utc: datetime


class BlueprintCard(BaseModel):
    blueprint_id: str
    content_version: str
    source_draft_id: str
    owner_player_id: str
    display_name: str
    avatar_url: str | None
    material_processing: Literal["stored_only"]
    created_at_utc: datetime


class CustomBlueprintView(BlueprintCard):
    content: AuthoringContent


class CandidateView(BaseModel):
    candidate_id: str
    draft_id: str
    input_revision: int
    operation: Literal["basic", "story", "interview", "calibrate"]
    status: Literal["processing", "completed", "failed"]
    error_code: str | None
    model_profile: str
    model_requests: int
    usage: dict[str, int]
    output: CandidateOutput | None
    frozen_input: dict
    deadline_utc: datetime
    created_at_utc: datetime
    finished_at_utc: datetime | None


class CandidateError(BaseModel):
    error: ErrorBody
    candidate_id: str


class GuidanceQuestion(BaseModel):
    id: str
    question: str
    theme: str | None = None


class AuthoringTemplateView(BaseModel):
    schema_version: int
    fixed_background_notice: str
    material_notice: str
    default_voice: str
    default_relational_dynamics: str
    guidance: list[GuidanceQuestion]
    interview: list[GuidanceQuestion]
    limits: dict[str, int]
    operations: dict[str, str]
