import asyncio
import logging
from datetime import UTC, datetime
from time import monotonic

from echo_commons.infrastructure.database.mapping import utc_datetime
from echo_commons.modules.memory.domain.cycles import PendingMaterials
from echo_commons.modules.memory.domain.policy import CyclePolicy
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.services.sealing import MemorySealing
from echo_commons.modules.reflection.workflow import ReflectionWorkflow
from echo_commons.shared.errors import ConflictError

logger = logging.getLogger("echo_commons.memory.scheduling")


class MemoryScheduling:
    def __init__(
        self, sealing: MemorySealing, workflow: ReflectionWorkflow, policy: CyclePolicy
    ) -> None:
        self.sealing, self.workflow, self.policy = sealing, workflow, policy
        self.database = sealing.database
        self._next_scan = 0.0

    async def run_once(self) -> bool:
        if monotonic() < self._next_scan:
            return False
        self._next_scan = monotonic() + self.policy.scan_seconds
        return bool(await asyncio.to_thread(self.scan, datetime.now(UTC)))

    def scan(self, now: datetime) -> int:
        with self.database.read() as connection:
            scopes = tuple(
                connection.execute(
                    "SELECT i.community_id,i.character_id,i.memory_mode FROM character_instances i "
                    "JOIN communities c USING(community_id) WHERE c.status='active' "
                    "AND i.memory_status='ready' ORDER BY i.community_id,i.character_id"
                )
            )
        created = 0
        for scope in scopes:
            identity = (scope["community_id"], scope["character_id"])
            try:
                if (
                    self.workflow.freeze_segment(
                        self.sealing,
                        *identity,
                        observed_at=now,
                        idle_seconds=self.policy.experience_idle_seconds,
                        automatic=True,
                    )
                    is not None
                ):
                    created += 1
                consumers = (
                    (SummaryConsumer.CONTINUITY, SummaryConsumer.ORGANIZATION)
                    if scope["memory_mode"] == "full"
                    else (SummaryConsumer.CONTINUITY,)
                )
                for consumer in consumers:
                    with self.database.read() as connection:
                        if self.workflow.blocked(connection, *identity, consumer.value):
                            continue
                        result = self.workflow.batches.select(
                            connection,
                            *identity,
                            consumer,
                            limit=self.workflow.batches.max_materials,
                            now=now,
                        )
                        if result is None:
                            continue
                        summaries, previous, full = result
                        chars = sum(len(item["summary_text"] or "") for item in summaries)
                        empty_continuity = consumer is SummaryConsumer.CONTINUITY and not chars
                        stats = PendingMaterials(
                            chars,
                            len(summaries),
                            min(utc_datetime(item["ingested_at_utc"]) for item in summaries),
                            full
                            or chars + sum(len(item["content"]) for item in previous)
                            >= self.workflow.batches.max_chars,
                        )
                        if not empty_continuity and not stats.due(
                            now,
                            target_chars=self.policy.summary_target_chars,
                            wait_seconds=self.policy.summary_wait_seconds,
                        ):
                            continue
                    if (
                        self.workflow.schedule_summaries(
                            *identity,
                            consumer,
                            limit=self.workflow.batches.max_materials,
                            automatic=True,
                            observed_at=now,
                        )
                        is not None
                    ):
                        created += 1
            except ConflictError as error:
                logger.warning(
                    "Memory scheduling source rejected: character=%s, code=%s",
                    scope["character_id"],
                    error.code,
                )
        return created
