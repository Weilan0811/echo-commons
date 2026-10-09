import asyncio
import base64
import binascii
import json
from collections.abc import AsyncIterator
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.realtime.broker import EventBroker
from echo_commons.infrastructure.realtime.repository import BATCH_SIZE
from echo_commons.infrastructure.realtime.retention import EventRetention
from echo_commons.shared.errors import InvalidCursor, NotFoundError
from echo_commons.shared.realtime import EventReference

HEARTBEAT_SECONDS = 15
SEND_TIMEOUT_SECONDS = 30


class EventCursor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    player_id: str
    community_id: str
    sequence: int = Field(ge=0)

    def encode(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode()

    @classmethod
    def decode(cls, value: str, player_id: str, community_id: str):
        try:
            cursor = cls.model_validate_json(base64.b64decode(value, altchars=b"-_", validate=True))
        except (ValueError, binascii.Error, ValidationError) as error:
            raise InvalidCursor("Invalid event cursor") from error
        if (cursor.player_id, cursor.community_id) != (player_id, community_id):
            raise InvalidCursor("Event cursor belongs to a different player or community")
        return cursor


class EventProjectionPort(Protocol):
    def require_member(self, connection, community_id: str, player_id: str) -> None: ...
    def project(self, connection, event: EventReference, player_id: str) -> dict | None: ...


class EventStream:
    def __init__(self, database: Database, projection: EventProjectionPort):
        self.database, self.projection = database, projection
        self.broker = EventBroker()
        self.retention = EventRetention(database)

    async def start(self):
        self.broker.start()
        self.database.after_commit = self.broker.notify
        await self.retention.start()

    async def close(self):
        self.broker.close()
        self.database.after_commit = None
        await self.retention.close()

    def current(self, community_id: str, player_id: str) -> EventCursor:
        with self.database.read() as connection:
            self.projection.require_member(connection, community_id, player_id)
            _, high = self.database.events.bounds(connection)
            return EventCursor(player_id=player_id, community_id=community_id, sequence=high)

    def validate(self, community_id: str, player_id: str, value: str) -> EventCursor:
        cursor = EventCursor.decode(value, player_id, community_id)
        current = self.current(community_id, player_id)
        if cursor.sequence > current.sequence:
            raise InvalidCursor("Event cursor is ahead of current state")
        return cursor

    def scan(self, cursor: EventCursor):
        with self.database.read() as connection:
            self.projection.require_member(connection, cursor.community_id, cursor.player_id)
            floor, high = self.database.events.bounds(connection)
            if cursor.sequence < floor:
                return [], cursor, False, True
            rows = self.database.events.read(connection, cursor.community_id, cursor.sequence)
            outgoing = []
            for row in rows:
                reference = self.database.events.reference(row)
                data = self.projection.project(connection, reference, cursor.player_id)
                if data is not None:
                    position = cursor.model_copy(update={"sequence": row["sequence"]})
                    outgoing.append(
                        {
                            "event": reference.kind,
                            "id": position.encode(),
                            "data": json.dumps(data, ensure_ascii=False),
                        }
                    )
            more = len(rows) == BATCH_SIZE
            through = rows[-1]["sequence"] if more else high
            next_cursor = cursor.model_copy(update={"sequence": through})
            if through > cursor.sequence and (
                not outgoing or outgoing[-1]["id"] != next_cursor.encode()
            ):
                outgoing.append({"event": "checkpoint", "id": next_cursor.encode(), "data": "{}"})
            return outgoing, next_cursor, more, False

    async def events(self, cursor: EventCursor) -> AsyncIterator[dict]:
        subscription = self.broker.subscribe(cursor.community_id)
        try:
            while not self.broker.closed:
                generation = subscription.generation
                try:
                    outgoing, cursor, more, expired = await asyncio.to_thread(self.scan, cursor)
                except NotFoundError:
                    yield {"event": "access_revoked", "data": '{"reason":"membership_required"}'}
                    return
                if expired:
                    yield {"event": "resync_required", "data": '{"reason":"cursor_expired"}'}
                    return
                for event in outgoing:
                    yield event
                if not more:
                    await self.broker.wait(subscription, generation)
        finally:
            self.broker.unsubscribe(cursor.community_id, subscription)
