import sqlite3

from echo_commons.modules.memory.repositories.author_batches import AuthorBatchRepository
from echo_commons.modules.memory.repositories.changes import MemoryChangeRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.perspective.contracts import ObservationScope, WorldReader
from echo_commons.modules.reflection.contracts.context import (
    AuthorMaterialSource,
    DigestMaterial,
    GraphContextSnapshot,
    MessageMaterial,
    SummaryMaterial,
    ThoughtMaterial,
)
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError


class ReflectionSourceUnavailable(ValueError):
    code = "reflection_source_unavailable"


class ReflectionSources:
    def __init__(
        self,
        perspective: WorldReader,
        segments: SegmentRepository,
        thoughts: ThoughtRepository,
        provenance: MemoryProvenanceRepository,
    ) -> None:
        self.perspective, self.segments = perspective, segments
        self.thoughts, self.provenance = thoughts, provenance

    def check_sources(self, connection: sqlite3.Connection, snapshot: GraphContextSnapshot) -> None:
        scope = snapshot.scope
        if snapshot.source_kind == "memory_change_set":
            try:
                MemoryChangeRepository().check(connection, snapshot)
            except ConflictError as error:
                raise ReflectionSourceUnavailable(str(error)) from error
            return
        observation = (
            self.perspective.observe(
                connection,
                ObservationScope(
                    scope.community_id,
                    snapshot.conversation_id,
                    ActorRef("character", scope.character_id),
                    snapshot.observation_upper_sequence,
                ),
            )
            if snapshot.conversation_id
            else None
        )
        visible = {message.message_id for message in observation.messages} if observation else set()
        if snapshot.source_kind == "author_material_batch":
            repository = AuthorBatchRepository()
            batch = repository.get(
                connection, scope.community_id, scope.character_id, snapshot.source_id
            )
            author_rows = {row["chunk_id"]: row for row in repository.materials(connection, batch)}
            if batch.source_version != snapshot.source_version:
                raise ReflectionSourceUnavailable("Frozen author batch version changed")
        if snapshot.source_kind == "memory_summary_batch":
            batch = self.provenance.get_batch(
                connection, scope.community_id, scope.character_id, snapshot.source_id
            )
            if batch.source_version != snapshot.source_version:
                raise ReflectionSourceUnavailable("Frozen summary batch version changed")
            self.provenance.batch_summaries(connection, batch)
        for material in snapshot.materials:
            if isinstance(material, AuthorMaterialSource):
                row = author_rows.get(material.source_id)
                valid = row is not None and row["blueprint_version"] == material.version
            elif isinstance(material, MessageMaterial):
                valid = material.source_id in visible and material.version == "1"
            elif isinstance(material, ThoughtMaterial):
                thought = self.thoughts.get(
                    connection, scope.community_id, scope.character_id, material.source_id
                )
                valid = (
                    thought["content"] is not None
                    and thought["content_version"] == material.version
                    and thought["conversation_id"] == snapshot.conversation_id
                )
            elif isinstance(material, SummaryMaterial):
                segment = self.segments.get(
                    connection, scope.community_id, scope.character_id, material.source_id
                )
                valid = (
                    segment.conversation_id == snapshot.conversation_id
                    and segment.status == "ingested"
                    and segment.summary_version == material.version
                    and segment.summary_text == material.content
                )
            elif isinstance(material, DigestMaterial):
                digest = self.provenance.get_digest(
                    connection,
                    scope.community_id,
                    scope.character_id,
                    snapshot.conversation_id,
                    material.source_id,
                )
                valid = digest["content_version"] == material.version
            if not valid:
                raise ReflectionSourceUnavailable("Frozen reflection source is unavailable")
