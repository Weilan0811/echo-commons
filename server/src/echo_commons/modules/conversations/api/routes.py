from typing import Annotated

from fastapi import APIRouter, Depends, Query

from echo_commons.app.composition import Application
from echo_commons.app.http import application_for
from echo_commons.modules.conversations.api.schemas import (
    ConversationView,
    CreateConversation,
    MembershipView,
    MessagePageView,
    MessageReceipt,
    MessageView,
    SendMessage,
)
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.shared.actors import ActorKind, ActorRef

router = APIRouter(prefix="/api", tags=["conversations"])
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.post(
    "/communities/{community_id}/conversations", status_code=201, response_model=ConversationView
)
def create_conversation(
    community_id: str, body: CreateConversation, application: ApplicationDependency
):
    conversation = application.conversations.create(
        community_id, body.kind, body.actors, conversation_id=body.conversation_id
    )
    return ConversationView.model_validate(conversation, from_attributes=True)


@router.get("/communities/{community_id}/conversations", response_model=list[ConversationView])
def list_conversations(community_id: str, application: ApplicationDependency):
    return [
        ConversationView.model_validate(item, from_attributes=True)
        for item in application.conversations.list(community_id)
    ]


@router.put(
    "/conversations/{conversation_id}/members/{actor_kind}/{actor_id}",
    response_model=MembershipView,
)
def join_member(
    conversation_id: str,
    actor_kind: ActorKind,
    actor_id: str,
    application: ApplicationDependency,
):
    community = application.conversations.community_id(conversation_id)
    member = application.conversations.join(
        community, conversation_id, ActorRef(actor_kind, actor_id)
    )
    return MembershipView.model_validate(member, from_attributes=True)


@router.delete(
    "/conversations/{conversation_id}/members/{actor_kind}/{actor_id}",
    response_model=MembershipView,
)
def leave_member(
    conversation_id: str,
    actor_kind: ActorKind,
    actor_id: str,
    application: ApplicationDependency,
):
    community = application.conversations.community_id(conversation_id)
    member = application.conversations.leave(
        community, conversation_id, ActorRef(actor_kind, actor_id)
    )
    return MembershipView.model_validate(member, from_attributes=True)


@router.post(
    "/conversations/{conversation_id}/messages", status_code=202, response_model=MessageReceipt
)
def send_message(conversation_id: str, body: SendMessage, application: ApplicationDependency):
    community = application.conversations.community_id(conversation_id)
    request = PlayerMessage(
        body.player_id,
        body.client_message_id,
        body.text,
        body.visibility,
        body.recipients,
        body.mentions,
        body.reply_to_message_id,
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
    community = application.conversations.community_id(conversation_id)
    page = application.messages.read(
        community, conversation_id, player_id, cursor=cursor, limit=limit
    )
    return MessagePageView(
        messages=tuple(
            MessageView.model_validate(item, from_attributes=True) for item in page.messages
        ),
        cursor=page.cursor,
        has_more=page.has_more,
    )
