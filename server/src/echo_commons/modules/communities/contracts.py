from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Protocol

from echo_commons.modules.communities.domain import Community, CommunityStatus, Player
from echo_commons.shared.actors import ActorRef


class CommunityReader(Protocol):
    def get(self, connection: sqlite3.Connection, community_id: str) -> Community: ...
    def require_member(
        self, connection: sqlite3.Connection, community_id: str, actor: ActorRef
    ) -> None: ...

    def player(self, connection: sqlite3.Connection, player_id: str) -> Player: ...


class CommunityLifecycle(Protocol):
    def community_changed(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        status: CommunityStatus,
        now: datetime,
    ) -> None: ...
