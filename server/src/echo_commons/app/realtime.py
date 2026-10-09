import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sse_starlette import EventSourceResponse

from echo_commons.app.composition import Application
from echo_commons.app.event_schemas import CursorResponse
from echo_commons.app.http import BUSINESS_RESPONSES, application_for
from echo_commons.infrastructure.realtime.stream import HEARTBEAT_SECONDS, SEND_TIMEOUT_SECONDS
from echo_commons.shared.errors import InvalidCursor

router = APIRouter(prefix="/api/communities", tags=["realtime"], responses=BUSINESS_RESPONSES)
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.get("/{community_id}/events/cursor", response_model=CursorResponse)
def event_cursor(community_id: str, player_id: str, application: ApplicationDependency):
    return CursorResponse(cursor=application.realtime.current(community_id, player_id).encode())


@router.get(
    "/{community_id}/events",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": "Player-visible SSE events",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def events(
    community_id: str,
    player_id: str,
    application: ApplicationDependency,
    cursor: str | None = None,
    last_event_id: Annotated[str | None, Header()] = None,
):
    value = last_event_id if last_event_id is not None else cursor
    if value is None:
        raise InvalidCursor("An initial event cursor is required")
    position = await asyncio.to_thread(
        application.realtime.validate, community_id, player_id, value
    )
    return EventSourceResponse(
        application.realtime.events(position),
        ping=HEARTBEAT_SECONDS,
        send_timeout=SEND_TIMEOUT_SECONDS,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
