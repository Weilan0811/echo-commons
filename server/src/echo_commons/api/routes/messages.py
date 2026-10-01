"""Message submission and cursor synchronization endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, status

from echo_server.api.dependencies import get_runtime
from echo_server.api.schemas.messages import (
    ChipsResponse,
    ErrorResponse,
    MessageResponse,
    MessageSenderResponse,
    SendMessageRequest,
    SendMessageResponse,
    SyncMessagesResponse,
)
from echo_server.domain.messages import (
    ConversationSyncQuery,
    MessageBatch,
    SubmitMessageCommand,
    SyncMessagesQuery,
)
from echo_server.runtime.application_runtime import ApplicationRuntime

router = APIRouter(tags=["messages"])


@router.post(
    "/message/send",
    response_model=SendMessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        409: {"model": ErrorResponse, "description": "Idempotency conflict"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Persistence unavailable"},
    },
)
async def send_message(
    request: SendMessageRequest,
    runtime: ApplicationRuntime = Depends(get_runtime),  # noqa: B008
) -> SendMessageResponse:
    receipt = await runtime.submit_message(
        SubmitMessageCommand(
            account_id=runtime.settings.account_id,
            conversation_id=request.conversation_id,
            player_text=request.player_text,
            images=tuple(request.images),
            client_msg_id=request.client_msg_id,
            local_timestamp=request.local_timestamp,
        )
    )
    return SendMessageResponse(
        accepted=receipt.accepted,
        message_id=receipt.message_id,
        client_msg_id=receipt.client_msg_id,
        trace_id=receipt.trace_id,
    )


@router.get(
    "/message/sync",
    response_model=SyncMessagesResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Persistence unavailable"},
    },
)
async def sync_messages(
    since: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    runtime: ApplicationRuntime = Depends(get_runtime),  # noqa: B008
) -> SyncMessagesResponse:
    batch = await runtime.sync_messages(
        SyncMessagesQuery(account_id=runtime.settings.account_id, since=since, limit=limit)
    )
    return _sync_response(batch)


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=SyncMessagesResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Persistence unavailable"},
    },
)
async def sync_conversation_messages(
    conversation_id: str = Path(min_length=1),
    since: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    runtime: ApplicationRuntime = Depends(get_runtime),  # noqa: B008
) -> SyncMessagesResponse:
    batch = await runtime.sync_conversation_messages(
        ConversationSyncQuery(
            account_id=runtime.settings.account_id,
            conversation_id=conversation_id,
            since=since,
            limit=limit,
        )
    )
    return _sync_response(batch)


def _sync_response(batch: MessageBatch) -> SyncMessagesResponse:
    return SyncMessagesResponse(
        messages=[
            MessageResponse(
                messageId=message.message_id,
                clientMsgId=message.client_msg_id,
                conversationId=message.conversation_id,
                sender=MessageSenderResponse(type=message.sender.type.value, id=message.sender.id),
                text=message.text,
                images=list(message.images),
                replyToMessageId=message.reply_to_message_id,
                serverTimestamp=message.server_timestamp_utc,
            )
            for message in batch.messages
        ],
        nextCursor=batch.next_cursor,
        chips=ChipsResponse(statusHint=None, suggestions=[]),
        traces=[],
    )
