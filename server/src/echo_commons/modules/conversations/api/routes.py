from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from echo_commons.app.composition import Application
from echo_commons.app.http import BUSINESS_RESPONSES, application_for
from echo_commons.modules.conversations.api.schemas import (
    ArchiveConversation,
    ConversationListPreference,
    ConversationView,
    CreateConversation,
    JoinMembership,
    MessageHistoryView,
    MessagePageView,
    MessageReceipt,
    PlayerConversationSummary,
    PlayerMessageView,
    ReadMarker,
    ReadState,
    SendMessage,
)
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.conversations.operations import (
    ArchiveOperation,
    ArchiveResult,
    ListPreferenceOperation,
    ListPreferenceResult,
    MembershipOperation,
    MembershipResult,
)
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.management import Page, PageOptions
from echo_commons.shared.public import PublicDisplay

router = APIRouter(prefix="/api", tags=["conversations"], responses=BUSINESS_RESPONSES)
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.post(
    "/communities/{community_id}/conversations", status_code=201, response_model=ConversationView
)
def create_conversation(
    community_id: str, body: CreateConversation, application: ApplicationDependency
):
    conversation = application.conversations.create(
        community_id,
        body.kind,
        body.actors,
        conversation_id=body.conversation_id,
        player_id=body.player_id,
    )
    return ConversationView.model_validate(conversation, from_attributes=True)


@router.get("/conversations", response_model=Page[PlayerConversationSummary])
def conversations(
    player_id: str,
    application: ApplicationDependency,
    community_id: str | None = None,
    membership: Literal["current", "past", "all"] = "current",
    status: Literal["active", "archived", "all"] = "active",
    view: Literal["active", "history", "hidden", "archived", "all"] | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return application.player_conversations.conversations_for(
        player_id,
        PageOptions(cursor=cursor, limit=limit),
        community_id=community_id,
        membership=membership,
        status=status,
        view=view,
    )


@router.post("/conversations/{conversation_id}/archive", response_model=ArchiveResult)
def archive_conversation(
    conversation_id: str, body: ArchiveConversation, application: ApplicationDependency
):
    return application.conversations.apply_list_operation(
        ArchiveOperation(
            community_id=application.conversations.community_id(conversation_id),
            conversation_id=conversation_id,
            player_id=body.player_id,
            expected_state_version=body.expected_state_version,
        ),
        body.client_operation_id,
    )


@router.put("/conversations/{conversation_id}/list-preference", response_model=ListPreferenceResult)
def list_preference(
    conversation_id: str, body: ConversationListPreference, application: ApplicationDependency
):
    return application.conversations.apply_list_operation(
        ListPreferenceOperation(
            community_id=application.conversations.community_id(conversation_id),
            conversation_id=conversation_id,
            player_id=body.player_id,
            hidden=body.hidden,
        ),
        body.client_operation_id,
    )


@router.get("/conversations/{conversation_id}", response_model=PlayerConversationSummary)
def conversation(conversation_id: str, player_id: str, application: ApplicationDependency):
    return application.player_conversations.conversation(conversation_id, player_id)


@router.get("/conversations/{conversation_id}/members", response_model=Page[PublicDisplay])
def members(
    conversation_id: str,
    player_id: str,
    application: ApplicationDependency,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return application.player_conversations.members(
        conversation_id, player_id, PageOptions(cursor=cursor, limit=limit)
    )


@router.put("/conversations/{conversation_id}/membership", response_model=MembershipResult)
def join(conversation_id: str, body: JoinMembership, application: ApplicationDependency):
    request = MembershipOperation(
        community_id=application.conversations.community_id(conversation_id),
        conversation_id=conversation_id,
        actor=ActorRef("player", body.player_id),
        action="join",
        player_id=body.player_id,
    )
    return application.conversations.apply_membership(request, body.client_operation_id)


@router.delete("/conversations/{conversation_id}/membership", response_model=MembershipResult)
def leave(
    conversation_id: str,
    application: ApplicationDependency,
    player_id: str = Query(min_length=1),
    expected_membership_id: str = Query(min_length=1),
    client_operation_id: str = Query(min_length=1),
):
    request = MembershipOperation(
        community_id=application.conversations.community_id(conversation_id),
        conversation_id=conversation_id,
        actor=ActorRef("player", player_id),
        action="leave",
        player_id=player_id,
        expected_membership_id=expected_membership_id,
    )
    return application.conversations.apply_membership(request, client_operation_id)


@router.post(
    "/conversations/{conversation_id}/messages", status_code=202, response_model=MessageReceipt
)
def send_message(conversation_id: str, body: SendMessage, application: ApplicationDependency):
    community = application.conversations.community_id(conversation_id)
    request = PlayerMessage(
        body.player_id,
        body.client_message_id,
        body.text,
        mentions=body.mentions,
        reply_to_message_id=body.reply_to_message_id,
    )
    message = application.intake.send(community, conversation_id, request)
    return MessageReceipt.model_validate(message, from_attributes=True)


@router.get("/conversations/{conversation_id}/messages", response_model=MessagePageView)
def read_messages(
    conversation_id: str,
    player_id: str,
    application: ApplicationDependency,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return application.player_conversations.read(
        conversation_id, player_id, cursor=cursor, limit=limit
    )


@router.get("/conversations/{conversation_id}/messages/history", response_model=MessageHistoryView)
def history(
    conversation_id: str,
    player_id: str,
    application: ApplicationDependency,
    older_cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return application.player_conversations.history(
        conversation_id, player_id, older_cursor=older_cursor, limit=limit
    )


@router.get(
    "/conversations/{conversation_id}/messages/{message_id}", response_model=PlayerMessageView
)
def message(
    conversation_id: str, message_id: str, player_id: str, application: ApplicationDependency
):
    return application.player_conversations.message(conversation_id, player_id, message_id)


@router.put("/conversations/{conversation_id}/read", response_model=ReadState)
def mark_read(conversation_id: str, body: ReadMarker, application: ApplicationDependency):
    return application.player_conversations.mark_read(
        conversation_id, body.player_id, body.through_message_id
    )
