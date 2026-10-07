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
                    "SELECT DISTINCT i.community_id,i.character_id,i.memory_mode, "
                    "v.conversation_id,v.next_sequence "
                    "FROM character_instances i JOIN communities c USING(community_id) "
                    "JOIN conversation_memberships m ON m.community_id=i.community_id "
                    "AND m.actor_kind='character' AND m.actor_id=i.character_id "
                    "JOIN conversations v USING(conversation_id) "
                    "WHERE c.status='active' AND i.memory_status='ready' "
                    "ORDER BY i.community_id,i.character_id,v.conversation_id"
                )
            )
        created = 0
        for scope in scopes:
            identity = (scope["community_id"], scope["character_id"], scope["conversation_id"])
            try:
                with self.database.read() as connection:
                    segment_due = False
                    if not self.workflow.blocked(connection, *identity, "segment_reflect"):
                        messages, thoughts = self.sealing.pending(
                            connection, *identity, scope["next_sequence"] - 1
                        )
                        if messages:
                            count = len(messages) + len(thoughts)
                            chars = sum(len(item.text) for item in messages) + sum(
                                len(item["content"]) for item in thoughts.values()
                            )
                            stats = PendingMaterials(
                                chars,
                                count,
                                messages[0].created_at_utc,
                                len(messages) >= self.sealing.max_messages
                                or count >= self.sealing.max_materials
                                or chars >= self.sealing.max_material_chars,
                            )
                            segment_due = stats.due(
                                now,
                                target_chars=self.policy.segment_target_chars,
                                wait_seconds=self.policy.segment_wait_seconds,
                            )
                if (
                    segment_due
                    and self.workflow.freeze_segment(self.sealing, *identity) is not None
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
                            through_sequence=scope["next_sequence"] - 1,
                            limit=self.workflow.batches.max_materials,
                        )
                        if result is None:
                            continue
                        summaries, previous, budget_full = result
                        chars = sum(len(item["summary_text"]) for item in summaries)
                        stats = PendingMaterials(
                            chars,
                            len(summaries),
                            min(utc_datetime(item["ingested_at_utc"]) for item in summaries),
                            budget_full
                            or len(summaries)
                            >= self.workflow.batches.max_materials - int(previous is not None)
                            or chars + (len(previous["content"]) if previous else 0)
                            >= self.workflow.batches.max_chars,
                        )
                        if not stats.due(
                            now,
                            target_chars=self.policy.summary_target_chars,
                            wait_seconds=self.policy.summary_wait_seconds,
                        ):
                            continue
                    if (
                        self.workflow.schedule_summaries(
                            *identity,
                            consumer,
                            through_sequence=scope["next_sequence"] - 1,
                            limit=self.workflow.batches.max_materials,
                            automatic=True,
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
