from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from echo_commons.app.composition import Application
from echo_commons.app.http import application_for
from echo_commons.app.management_schemas import (
    CharacterDetail,
    CommunityMemberView,
    ConversationDetail,
    ErrorResponse,
    EvidenceView,
    ExportRequest,
    ExportView,
    InspectedContext,
    MemberInterval,
    MemoryDetail,
    MemorySummary,
    MessageDetail,
    MessageSummary,
    NodeInspection,
    ReflectionDetail,
    ReflectionSummary,
    RelationshipInspection,
    ScheduleResult,
    SealRequest,
    SealResult,
    SegmentReflectionRequest,
    StateInspection,
    SummaryReflectionRequest,
    TaskDetail,
    TaskSummary,
    TraceInspection,
    TurnDetail,
    TurnSummary,
)
from echo_commons.modules.communities.api.schemas import CommunityView, PlayerView
from echo_commons.modules.conversations.domain.task import TaskStatus
from echo_commons.modules.memory.management import MemoryCollection
from echo_commons.shared.actors import ActorKind
from echo_commons.shared.management import Page, PageOptions

router = APIRouter(
    prefix="/internal",
    tags=["management"],
    responses={
        400: {"model": ErrorResponse, "description": "业务输入或游标无效"},
        404: {"model": ErrorResponse, "description": "对象不存在或不属于请求范围"},
        409: {"model": ErrorResponse, "description": "材料或执行状态冲突"},
        500: {"model": ErrorResponse, "description": "响应或存储不可用"},
        503: {"model": ErrorResponse, "description": "存储暂时不可用"},
    },
)
ApplicationDependency = Annotated[Application, Depends(application_for)]


def page_options(cursor: str | None = None, limit: int = Query(default=50, ge=1, le=200)):
    return PageOptions(cursor=cursor, limit=limit)


Pagination = Annotated[PageOptions, Depends(page_options)]
GraphStatus = Literal[
    "pending", "running", "retry_wait", "completed", "partial", "failed", "cancelled"
]


@router.get("/communities", response_model=Page[CommunityView])
def communities(application: ApplicationDependency, page: Pagination):
    return application.community_management.communities(page)


@router.get("/communities/{community_id}", response_model=CommunityView)
def community(community_id: str, application: ApplicationDependency):
    return application.community_management.community(community_id)


@router.get("/players", response_model=Page[PlayerView])
def players(application: ApplicationDependency, page: Pagination):
    return application.community_management.players(page)


@router.get("/players/{player_id}", response_model=PlayerView)
def player(player_id: str, application: ApplicationDependency):
    return application.community_management.player(player_id)


@router.get("/communities/{community_id}/members", response_model=Page[CommunityMemberView])
def community_members(community_id: str, application: ApplicationDependency, page: Pagination):
    return application.community_management.members(community_id, page)


@router.get("/communities/{community_id}/characters/{character_id}", response_model=CharacterDetail)
def character(community_id: str, character_id: str, application: ApplicationDependency):
    return application.character_management.character(community_id, character_id)


@router.get(
    "/communities/{community_id}/characters/{character_id}/states", response_model=StateInspection
)
def states(
    community_id: str, character_id: str, application: ApplicationDependency, page: Pagination
):
    return application.character_management.states(community_id, character_id, page)


@router.get(
    "/communities/{community_id}/characters/{character_id}/relationships",
    response_model=Page[RelationshipInspection],
)
def relationships(
    community_id: str, character_id: str, application: ApplicationDependency, page: Pagination
):
    return application.character_management.relationships(community_id, character_id, page)


@router.get(
    "/communities/{community_id}/characters/{character_id}/relationships/"
    "{target_kind}/{target_id}/evidence",
    response_model=Page[EvidenceView],
)
def evidence(
    community_id: str,
    character_id: str,
    target_kind: ActorKind,
    target_id: str,
    application: ApplicationDependency,
    page: Pagination,
):
    return application.character_management.evidence(
        community_id,
        character_id,
        target_kind,
        target_id,
        page,
    )


@router.get(
    "/communities/{community_id}/conversations/{conversation_id}", response_model=ConversationDetail
)
def conversation(community_id: str, conversation_id: str, application: ApplicationDependency):
    return application.conversation_management.conversation(community_id, conversation_id)


@router.get(
    "/communities/{community_id}/conversations/{conversation_id}/members",
    response_model=Page[MemberInterval],
)
def members(
    community_id: str, conversation_id: str, application: ApplicationDependency, page: Pagination
):
    return application.conversation_management.members(community_id, conversation_id, page)


@router.get(
    "/communities/{community_id}/conversations/{conversation_id}/messages",
    response_model=Page[MessageSummary],
)
def messages(
    community_id: str, conversation_id: str, application: ApplicationDependency, page: Pagination
):
    return application.conversation_management.messages(community_id, conversation_id, page)


@router.get(
    "/communities/{community_id}/conversations/{conversation_id}/messages/{message_id}",
    response_model=MessageDetail,
)
def message(
    community_id: str, conversation_id: str, message_id: str, application: ApplicationDependency
):
    return application.conversation_management.message(community_id, conversation_id, message_id)


@router.get(
    "/communities/{community_id}/conversations/{conversation_id}/turns",
    response_model=Page[TurnSummary],
)
def turns(
    community_id: str, conversation_id: str, application: ApplicationDependency, page: Pagination
):
    return application.conversation_management.turns(community_id, conversation_id, page)


@router.get(
    "/communities/{community_id}/conversations/{conversation_id}/turns/{turn_id}",
    response_model=TurnDetail,
)
def turn(community_id: str, conversation_id: str, turn_id: str, application: ApplicationDependency):
    return application.conversation_management.turn(community_id, conversation_id, turn_id)


@router.get("/communities/{community_id}/tasks", response_model=Page[TaskSummary])
def tasks(
    community_id: str,
    application: ApplicationDependency,
    page: Pagination,
    conversation_id: str | None = None,
    character_id: str | None = None,
    status: TaskStatus | None = None,
):
    return application.conversation_management.task_list(
        community_id,
        page,
        conversation_id=conversation_id,
        character_id=character_id,
        status=status,
    )


@router.get("/characters/{character_id}/tasks/{task_id}", response_model=TaskDetail)
def task(character_id: str, task_id: str, community_id: str, application: ApplicationDependency):
    return application.conversation_management.task(community_id, character_id, task_id)


@router.get("/characters/{character_id}/tasks/{task_id}/context", response_model=InspectedContext)
def context(character_id: str, task_id: str, community_id: str, application: ApplicationDependency):
    return application.conversation_diagnostics.context(community_id, character_id, task_id)


@router.get(
    "/communities/{community_id}/characters/{character_id}/memory/{collection}",
    response_model=Page[MemorySummary],
)
def memory_records(
    community_id: str,
    character_id: str,
    collection: MemoryCollection,
    application: ApplicationDependency,
    page: Pagination,
    conversation_id: str | None = None,
):
    return application.memory_management.list(
        community_id,
        character_id,
        collection,
        page,
        conversation_id=conversation_id,
    )


@router.get(
    "/communities/{community_id}/characters/{character_id}/memory/{collection}/{record_id}",
    response_model=MemoryDetail,
)
def memory_record(
    community_id: str,
    character_id: str,
    collection: MemoryCollection,
    record_id: str,
    application: ApplicationDependency,
):
    return application.memory_management.get(community_id, character_id, collection, record_id)


@router.get(
    "/communities/{community_id}/characters/{character_id}/reflection/runs",
    response_model=Page[ReflectionSummary],
)
def reflection_runs(
    community_id: str,
    character_id: str,
    application: ApplicationDependency,
    page: Pagination,
    status: GraphStatus | None = None,
):
    return application.reflection_view.list(community_id, character_id, page, status=status)


@router.get("/reflection/runs/{graph_run_id}", response_model=ReflectionDetail)
def reflection_run(
    graph_run_id: str, community_id: str, character_id: str, application: ApplicationDependency
):
    return application.reflection_view.get(community_id, character_id, graph_run_id)


@router.get(
    "/reflection/runs/{graph_run_id}/nodes/{node_task_id}/input", response_model=NodeInspection
)
def node_input(
    graph_run_id: str,
    node_task_id: str,
    community_id: str,
    character_id: str,
    application: ApplicationDependency,
):
    return application.reflection_view.node_input(
        community_id,
        character_id,
        graph_run_id,
        node_task_id,
    )


@router.get("/traces/{correlation_id}", response_model=TraceInspection)
def traces(
    correlation_id: str,
    community_id: str,
    application: ApplicationDependency,
    character_id: str | None = None,
):
    return {
        "correlation_id": correlation_id,
        "traces": application.trace_query.scoped(community_id, correlation_id, character_id),
    }


@router.post(
    "/communities/{community_id}/characters/{character_id}/conversations/"
    "{conversation_id}/segments",
    response_model=SealResult,
)
def seal(
    community_id: str,
    character_id: str,
    conversation_id: str,
    body: SealRequest,
    application: ApplicationDependency,
):
    segment = application.memory_sealing.seal(
        community_id,
        character_id,
        conversation_id,
        first_sequence=body.first_sequence,
        upper_sequence=body.through_sequence,
    )
    return {
        "outcome": "sealed" if segment else "no_material",
        "segment": application.memory_management.get(
            community_id,
            character_id,
            MemoryCollection.SEGMENTS,
            segment.segment_id,
        )
        if segment
        else None,
    }


@router.post(
    "/communities/{community_id}/characters/{character_id}/reflection/segments",
    status_code=202,
    response_model=ScheduleResult,
)
def schedule_segment(
    community_id: str,
    character_id: str,
    body: SegmentReflectionRequest,
    application: ApplicationDependency,
):
    run = application.reflection_workflow.schedule_segment(
        community_id, character_id, body.segment_id
    )
    return application.reflection_view.scheduling_result(run)


@router.post(
    "/communities/{community_id}/characters/{character_id}/reflection/summaries",
    status_code=202,
    response_model=ScheduleResult,
)
def schedule_summaries(
    community_id: str,
    character_id: str,
    body: SummaryReflectionRequest,
    application: ApplicationDependency,
):
    run = application.reflection_workflow.schedule_summaries(
        community_id,
        character_id,
        body.conversation_id,
        body.consumer,
        through_sequence=body.through_sequence,
        limit=body.limit,
    )
    if run is None:
        return {"outcome": "no_material", "graph_run": None, "source_kind": None, "source_id": None}
    return application.reflection_view.scheduling_result(run)


@router.post(
    "/reflection/runs/{graph_run_id}/restart", status_code=202, response_model=ScheduleResult
)
def restart(
    graph_run_id: str, community_id: str, character_id: str, application: ApplicationDependency
):
    run = application.reflection.restart(community_id, character_id, graph_run_id)
    return application.reflection_view.scheduling_result(run, restarted=True)


@router.post(
    "/communities/{community_id}/conversations/{conversation_id}/export", response_model=ExportView
)
def export(
    community_id: str,
    conversation_id: str,
    body: ExportRequest,
    application: ApplicationDependency,
    response: Response,
):
    result = application.conversation_export.export(
        community_id,
        conversation_id,
        first_sequence=body.first_sequence,
        through_sequence=body.through_sequence,
        character_id=body.character_id,
    )
    response.headers["Content-Disposition"] = 'attachment; filename="echo-commons-materials.json"'
    return result
