import sqlite3
from datetime import datetime
from typing import Protocol

from echo_commons.modules.characters.templates.catalog import MemoryPreloadResource
from echo_commons.modules.memory.domain.authored import AuthorMaterial
from echo_commons.modules.memory.domain.memory import MemorySegment
from echo_commons.modules.memory.domain.organization import (
    MemoryEdgeDraft,
    MemoryEntityDraft,
    MemoryEntryDraft,
)
from echo_commons.modules.memory.domain.views import MemoryViewDraft, ViewBranchResult


class MemoryBootstrapper(Protocol):
    def prepare(
        self,
        connection: sqlite3.Connection,
        character_id: str,
        blueprint_id: str,
        blueprint_version: str,
        materials: tuple[AuthorMaterial, ...],
        now: datetime,
    ) -> None: ...

    def retry(self, connection: sqlite3.Connection, character_id: str, now: datetime) -> None: ...

    def seed(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        resource: MemoryPreloadResource | None,
        now: datetime,
    ) -> None: ...


class MemoryChangeWriter(Protocol):
    def record(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        fact_kind: str,
        source_id: str,
        version: str | int,
        now: datetime,
    ) -> None: ...


class MemoryViewWriter(Protocol):
    def apply(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        batch_id: str,
        source_version: str,
        views: tuple[MemoryViewDraft, ...],
        produced: bool,
        now: datetime,
        *,
        view_results: tuple[ViewBranchResult, ...] = (),
    ) -> None: ...


class MemorySegmentWriter(Protocol):
    def ingest(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        segment_id: str,
        summary: str | None,
        now: datetime,
    ) -> MemorySegment: ...


class MemoryContinuityWriter(Protocol):
    def compress(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        batch_id: str,
        content: str | None,
        covers_through_sequence: int,
        now: datetime,
    ) -> None: ...


class MemoryOrganizationWriter(Protocol):
    def organize(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        batch_id: str,
        entries: tuple[MemoryEntryDraft, ...],
        entities: tuple[MemoryEntityDraft, ...],
        edges: tuple[MemoryEdgeDraft, ...],
        no_op: bool,
        now: datetime,
    ) -> None: ...
