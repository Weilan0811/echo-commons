from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.memory.services.sealing import MemorySealing
from echo_commons.modules.reflection.coordinator import ReflectionCoordinator
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind, ReflectionGraphRun
from echo_commons.modules.reflection.policy import require_graph


class ReflectionWorkflow:
    def __init__(self, coordinator: ReflectionCoordinator, batches: SummaryBatches) -> None:
        self.coordinator, self.batches = coordinator, batches

    def blocked(self, connection, community_id, character_id, kind):
        return self.coordinator.runs.blocks_consumer(
            connection, community_id, character_id, ReflectionGraphKind(kind)
        )

    def freeze_segment(
        self,
        sealing: MemorySealing,
        community_id: str,
        character_id: str,
        *,
        observed_at=None,
        idle_seconds=None,
        automatic=False,
    ) -> ReflectionGraphRun | None:
        with self.coordinator.database.transaction() as connection:
            if self.blocked(
                connection,
                community_id,
                character_id,
                ReflectionGraphKind.SEGMENT_REFLECT,
            ):
                return None
            require_graph(
                InstanceRepository().get(connection, community_id, character_id),
                ReflectionGraphKind.SEGMENT_REFLECT,
            )
            segment = sealing.freeze(
                connection,
                community_id,
                character_id,
                observed_at=observed_at,
                idle_seconds=idle_seconds,
                automatic=automatic,
            )
            if segment is None:
                return None
            return self.coordinator.start_segment_in(
                connection, community_id, character_id, segment.segment_id
            )

    def schedule_segment(
        self, community_id: str, character_id: str, segment_id: str
    ) -> ReflectionGraphRun:
        return self.coordinator.start_segment(community_id, character_id, segment_id)

    def schedule_summaries(
        self,
        community_id: str,
        character_id: str,
        consumer: SummaryConsumer,
        *,
        limit: int = 16,
        automatic: bool = False,
        observed_at=None,
    ) -> ReflectionGraphRun | None:
        consumer = SummaryConsumer(consumer)
        kind = (
            ReflectionGraphKind.CONTINUITY_COMPRESS
            if consumer is SummaryConsumer.CONTINUITY
            else ReflectionGraphKind.MEMORY_ORGANIZE
        )
        with self.coordinator.database.transaction() as connection:
            if automatic and self.blocked(connection, community_id, character_id, kind):
                return None
            require_graph(InstanceRepository().get(connection, community_id, character_id), kind)
            batch = self.batches.freeze_in(
                connection,
                community_id,
                character_id,
                consumer,
                limit=limit,
                observed_at=observed_at,
            )
            if batch is None:
                return None
            return self.coordinator.start_summary_in(
                connection, community_id, character_id, batch.batch_id, kind
            )
