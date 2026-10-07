from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Protocol

from echo_commons.modules.characters.domain.changes import RelationshipChange, StateChange
from echo_commons.modules.characters.domain.instance import CharacterInstance
from echo_commons.modules.characters.domain.state import StateEntry, StateKind
from echo_commons.shared.actors import ActorRef


class InstanceReader(Protocol):
    def get(
        self, connection: sqlite3.Connection, community_id: str, character_id: str
    ) -> CharacterInstance: ...


class StateReader(Protocol):
    def latest(
        self, connection: sqlite3.Connection, character_id: str, kind: StateKind, at: datetime
    ) -> StateEntry | None: ...


class CharacterIdentityReader(Protocol):
    def name(self, connection: sqlite3.Connection, community_id: str, character_id: str) -> str: ...


class CharacterFactWriter(Protocol):
    def refresh_attitude(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        target: ActorRef,
        content: str,
        observed_at: datetime,
        now: datetime,
        *,
        evidence_ids: tuple[str, ...] | None = None,
    ) -> None: ...

    def apply(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        source_kind: str,
        source_ref: str,
        relationships: tuple[RelationshipChange, ...],
        states: tuple[StateChange, ...],
        now: datetime,
    ) -> None: ...
