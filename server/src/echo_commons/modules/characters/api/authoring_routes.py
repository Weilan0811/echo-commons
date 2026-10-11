from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from echo_commons.app.composition import Application
from echo_commons.app.http import BUSINESS_RESPONSES, ErrorResponse, application_for
from echo_commons.modules.characters.api.authoring_schemas import (
    AuthoringTemplateView,
    BlueprintCard,
    CandidateError,
    CandidateView,
    ConfirmDocuments,
    ConfirmDraft,
    CopyDraft,
    CreateDraft,
    CustomBlueprintView,
    DraftAction,
    DraftView,
    GenerateCandidate,
    TemplateDocumentsView,
    UpdateDraft,
)
from echo_commons.modules.characters.domain.authoring import InterviewSelectionInvalid, Stage
from echo_commons.modules.characters.templates.authoring import authoring_template
from echo_commons.shared.management import Page, PageOptions

router = APIRouter(prefix="/api", tags=["character-authoring"], responses=BUSINESS_RESPONSES)
App = Annotated[Application, Depends(application_for)]
Player = Annotated[str, Query(min_length=1)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/character-authoring/template", response_model=AuthoringTemplateView)
def template():
    return authoring_template()


@router.post(
    "/character-drafts",
    response_model=DraftView,
    status_code=201,
    responses={200: {"model": DraftView}},
)
def create(body: CreateDraft, application: App, response: Response):
    try:
        content = body.content()
    except ValidationError as error:
        # 这是请求组合生成的校验，不能让全局响应校验处理器误报为服务故障。
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "authoring_input_invalid",
                    "message": "材料无法生成合法人物正文，请提供明确 profile 或调整材料："
                    + str(error),
                }
            },
        )
    value, created = application.authoring.create(
        body.player_id,
        str(body.draft_id),
        content,
        create_request=body.model_dump(mode="json"),
    )
    response.status_code = 201 if created else 200
    return value


@router.get("/character-drafts", response_model=Page[DraftView])
def drafts(application: App, player_id: Player, limit: Limit = 20, cursor: str | None = None):
    return application.authoring.page(player_id, PageOptions(limit=limit, cursor=cursor))


@router.get("/character-drafts/{draft_id}", response_model=DraftView)
def draft(draft_id: UUID, player_id: Player, application: App):
    return application.authoring.get(player_id, str(draft_id))


@router.put("/character-drafts/{draft_id}", response_model=DraftView)
def update(draft_id: UUID, body: UpdateDraft, application: App):
    return application.authoring.update(
        body.player_id,
        str(draft_id),
        body.expected_revision,
        body.content,
    )


@router.post(
    "/character-drafts/{draft_id}/confirm",
    response_model=CustomBlueprintView,
    status_code=201,
    responses={200: {"model": CustomBlueprintView}},
)
def confirm(draft_id: UUID, body: ConfirmDraft, application: App, response: Response):
    value, created = application.authoring.confirm(
        body.player_id,
        str(draft_id),
        body.expected_revision,
    )
    response.status_code = 201 if created else 200
    return value


@router.post(
    "/character-drafts/{draft_id}/copy",
    response_model=DraftView,
    status_code=201,
    responses={200: {"model": DraftView}},
)
def copy(draft_id: UUID, body: CopyDraft, application: App, response: Response):
    value, created = application.authoring.copy(body.player_id, str(draft_id), str(body.draft_id))
    response.status_code = 201 if created else 200
    return value


@router.get("/custom-blueprints", response_model=Page[BlueprintCard])
def blueprints(application: App, player_id: Player, limit: Limit = 20, cursor: str | None = None):
    return application.authoring.page(
        player_id,
        PageOptions(limit=limit, cursor=cursor),
        blueprints=True,
    )


@router.get("/custom-blueprints/{blueprint_id}", response_model=CustomBlueprintView)
def blueprint(blueprint_id: str, player_id: Player, application: App):
    return application.authoring.blueprint(player_id, blueprint_id)


@router.post(
    "/character-drafts/{draft_id}/candidates",
    response_model=CandidateView,
    status_code=201,
    responses={
        200: {"model": CandidateView},
        409: {"model": CandidateError | ErrorResponse},
        502: {"model": CandidateError},
        503: {"model": CandidateError | ErrorResponse},
        504: {"model": CandidateError},
    },
)
async def generate(draft_id: UUID, body: GenerateCandidate, application: App, response: Response):
    try:
        value, status = await application.authoring.generate(
            body.player_id,
            str(draft_id),
            body.request(),
        )
    except InterviewSelectionInvalid as error:
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {
                        "type": "value_error",
                        "loc": ["body", "question_ids"],
                        "msg": str(error),
                        "input": list(body.question_ids),
                    }
                ]
            },
        )
    response.status_code = status
    if status >= 400:
        return JSONResponse(
            status_code=status,
            content={
                "error": {"code": value["error_code"], "message": "人物候选生成未完成，草稿已保留"},
                "candidate_id": value["candidate_id"],
            },
        )
    return value


@router.get("/character-drafts/{draft_id}/candidates/{candidate_id}", response_model=CandidateView)
def candidate(draft_id: UUID, candidate_id: UUID, player_id: Player, application: App):
    return application.authoring.candidate(player_id, str(draft_id), str(candidate_id))


@router.post("/character-drafts/{draft_id}/stages/{stage}/confirm", response_model=DraftView)
def confirm_stage(draft_id: UUID, stage: Stage, body: DraftAction, application: App):
    return application.authoring.confirm_stage(
        body.player_id, str(draft_id), body.expected_revision, stage
    )


@router.post("/character-drafts/{draft_id}/documents/confirm", response_model=DraftView)
def confirm_documents(draft_id: UUID, body: ConfirmDocuments, application: App):
    return application.authoring.confirm_documents(
        body.player_id, str(draft_id), body.expected_revision
    )


@router.post(
    "/character-drafts/{draft_id}/documents/template", response_model=TemplateDocumentsView
)
def template_documents(draft_id: UUID, body: DraftAction, application: App):
    return application.authoring.template_documents(
        body.player_id, str(draft_id), body.expected_revision
    )


@router.post("/character-drafts/{draft_id}/documents/template/accept", response_model=DraftView)
def accept_template_documents(draft_id: UUID, body: DraftAction, application: App):
    return application.authoring.template_documents(
        body.player_id, str(draft_id), body.expected_revision, accept=True
    )


@router.post(
    "/character-drafts/{draft_id}/candidates/{candidate_id}/accept", response_model=DraftView
)
def accept_candidate(draft_id: UUID, candidate_id: UUID, body: DraftAction, application: App):
    return application.authoring.accept(
        body.player_id, str(draft_id), body.expected_revision, str(candidate_id)
    )
