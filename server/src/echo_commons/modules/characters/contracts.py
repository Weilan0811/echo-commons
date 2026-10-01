from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Protocol

from echo_commons.modules.characters.domain.instance import CharacterInstance
from echo_commons.modules.characters.domain.state import StateEntry, StateKind


class InstanceReader(Protocol):
    def get(
        self, connection: sqlite3.Connection, community_id: str, character_id: str
    ) -> CharacterInstance: ...


class StateReader(Protocol):
    def latest(
        self, connection: sqlite3.Connection, character_id: str, kind: StateKind, at: datetime
    ) -> StateEntry | None: ...
