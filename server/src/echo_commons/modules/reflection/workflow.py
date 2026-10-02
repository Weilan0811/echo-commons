from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.reflection.coordinator import ReflectionCoordinator
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind, ReflectionGraphRun


class ReflectionWorkflow:
    def __init__(self, coordinator: ReflectionCoordinator, batches: SummaryBatches) -> None:
        self.coordinator, self.batches = coordinator, batches

    def schedule_segment(
        self, community_id: str, character_id: str, segment_id: str
    ) -> ReflectionGraphRun:
        return self.coordinator.start_segment(community_id, character_id, segment_id)

    def schedule_summaries(
        self,
        community_id: str,
        character_id: str,
        conversation_id: str,
        consumer: SummaryConsumer,
        *,
        through_sequence: int,
        limit: int = 16,
    ) -> ReflectionGraphRun | None:
        consumer = SummaryConsumer(consumer)
        batch = self.batches.freeze(
            community_id,
            character_id,
            conversation_id,
            consumer,
            through_sequence=through_sequence,
            limit=limit,
        )
        if batch is None:
            return None
        kind = (
            ReflectionGraphKind.CONTINUITY_COMPRESS
            if consumer is SummaryConsumer.CONTINUITY
            else ReflectionGraphKind.MEMORY_ORGANIZE
        )
        return self.coordinator.start_summary(community_id, character_id, batch.batch_id, kind)
