from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from echo_commons.app.composition import Application
from echo_commons.app.http import ErrorResponse, application_for
from echo_commons.app.management_schemas import (
    CharacterDetail,
    CommunityMemberView,
    ConversationDetail,
    CoreMemoryInspection,
    CoreRefreshRequest,
    EvidenceView,
    ExportRequest,
    ExportView,
    InspectedContext,
    ManagementCandidateView,
    ManagementCharacterView,
    ManagementGenerationView,
    MemberInterval,
    MemoryDetail,
    MemoryIndexStatus,
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
from echo_commons.modules.conversations.api.schemas import ConversationView, ManageMembership
from echo_commons.modules.conversations.domain.task import TaskStatus
from echo_commons.modules.conversations.member_operations import (
    MembershipOperation,
    MembershipResult,
)
from echo_commons.modules.maintenance.contracts import CleanupError, CleanupRequest, CleanupResult
from echo_commons.modules.memory.management import MemoryCollection
from echo_commons.modules.reflection.views import ViewScheduling
from echo_commons.shared.actors import ActorKind, ActorRef
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


@router.get("/players/{player_id}/image-generations", response_model=Page[ManagementGenerationView])
def image_generations(player_id: str, application: ApplicationDependency, page: Pagination):
    return application.image_generations.management_page(player_id, page)


@router.get(
    "/players/{player_id}/character-candidates", response_model=Page[ManagementCandidateView]
)
def character_candidates(player_id: str, application: ApplicationDependency, page: Pagination):
    return application.authoring.management_candidates(player_id, page)


@router.post(
    "/maintenance/cleanup",
    response_model=CleanupResult,
    response_model_exclude_none=True,
    responses={409: {"model": CleanupResult, "description": "清理被运行状态或引用阻止"}},
)
def cleanup(body: CleanupRequest, response: Response, application: ApplicationDependency):
    result = application.maintenance.cleanup(body)
    if not body.dry_run and result.blockers:
        response.status_code = 409
        result.error = CleanupError()
    return result


@router.get("/communities/{community_id}/characters", response_model=Page[ManagementCharacterView])
def characters(community_id: str, application: ApplicationDependency, page: Pagination):
    return application.character_management.characters(community_id, page)


@router.get("/communities/{community_id}/conversations", response_model=Page[ConversationView])
def conversations(
    community_id: str,
    application: ApplicationDependency,
    page: Pagination,
    kind: Literal["direct", "group"] | None = None,
    status: Literal["active", "archived"] | None = None,
):
    return application.conversation_management.conversations_for(
        community_id, page, kind=kind, status=status
    )


@router.put(
    "/communities/{community_id}/conversations/{conversation_id}/members/{actor_kind}/{actor_id}",
    response_model=MembershipResult,
)
def join_member(
    community_id: str,
    conversation_id: str,
    actor_kind: ActorKind,
    actor_id: str,
    body: ManageMembership,
    application: ApplicationDependency,
):
    request = MembershipOperation(
        community_id=community_id,
        conversation_id=conversation_id,
        actor=ActorRef(actor_kind, actor_id),
        action="join",
        expected_membership_version=body.expected_membership_version,
    )
    return application.conversations.apply_membership(request, body.client_operation_id)


@router.delete(
    "/communities/{community_id}/conversations/{conversation_id}/members/{actor_kind}/{actor_id}",
    response_model=MembershipResult,
)
def leave_member(
    community_id: str,
    conversation_id: str,
    actor_kind: ActorKind,
    actor_id: str,
    application: ApplicationDependency,
    expected_membership_version: int = Query(ge=0),
    client_operation_id: str = Query(min_length=1),
):
    request = MembershipOperation(
        community_id=community_id,
        conversation_id=conversation_id,
        actor=ActorRef(actor_kind, actor_id),
        action="leave",
        expected_membership_version=expected_membership_version,
    )
    return application.conversations.apply_membership(request, client_operation_id)


@router.get("/communities", response_model=Page[CommunityView])
def communities(application: ApplicationDependency, page: Pagination, q: str = ""):
    return application.community_management.communities(page, q)


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
def task(
    character_id: str,
    task_id: str,
    community_id: str,
    application: ApplicationDependency,
    page: Pagination,
):
    return application.conversation_management.task(community_id, character_id, task_id, page)


@router.get("/characters/{character_id}/tasks/{task_id}/context", response_model=InspectedContext)
def context(character_id: str, task_id: str, community_id: str, application: ApplicationDependency):
    return application.conversation_diagnostics.context(community_id, character_id, task_id)


@router.get("/characters/{character_id}/memory-index", response_model=MemoryIndexStatus)
def memory_index(character_id: str, community_id: str, application: ApplicationDependency):
    return application.memory_management.index_status(community_id, character_id) | {
        "vector_enabled": application.settings.memory.vector.enabled,
        "model_identity": application.embeddings.identity if application.embeddings else None,
    }


@router.post("/characters/{character_id}/memory-index/rebuild", response_model=MemoryIndexStatus)
def rebuild_memory_index(character_id: str, community_id: str, application: ApplicationDependency):
    with application.database.transaction() as connection:
        application.memory_indexing.rebuild(connection, community_id, character_id)
    return memory_index(character_id, community_id, application)


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
    page: Pagination,
):
    return application.reflection_view.node_input(
        community_id,
        character_id,
        graph_run_id,
        node_task_id,
        page,
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
    "/communities/{community_id}/characters/{character_id}/reflection/core-memory",
    status_code=202,
    response_model=ScheduleResult,
)
def refresh_core_memory(
    community_id: str,
    character_id: str,
    body: CoreRefreshRequest,
    application: ApplicationDependency,
):
    run = ViewScheduling(application.reflection).refresh_core(
        community_id, character_id, str(body.request_id)
    )
    return application.reflection_view.scheduling_result(run)


@router.get(
    "/communities/{community_id}/characters/{character_id}/reflection/core-memory",
    response_model=CoreMemoryInspection,
)
def inspect_core_memory(
    community_id: str,
    character_id: str,
    application: ApplicationDependency,
):
    return application.memory_management.core_memory(community_id, character_id) | {
        "max_chars": application.settings.reflection_core_memory_max_chars,
    }


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
