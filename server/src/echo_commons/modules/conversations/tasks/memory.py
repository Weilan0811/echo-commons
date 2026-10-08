import asyncio
from datetime import UTC, datetime

from echo_commons.agents.contracts.context import ContextSnapshot, MemoryItem
from echo_commons.agents.contracts.input import SourceVersion
from echo_commons.agents.contracts.output import (
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval, SearchScope
from echo_commons.shared.errors import ConflictError


class ContextBudgetExceeded(ValueError):
    def __init__(self, snapshot: ContextSnapshot) -> None:
        super().__init__("Persona and current input exceed configured context budget")
        self.snapshot = snapshot


def budget_snapshot(snapshot: ContextSnapshot, max_chars: int) -> ContextSnapshot:
    outputs = OutputRegistry()
    outputs.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)

    def size(value):
        prompt = project_snapshot(
            value, output_contract=CHARACTER_MESSAGE_CONTRACT, outputs=outputs
        )
        return sum(len(item.content) for item in prompt.messages)

    current = snapshot
    # 人设和本次输入固定保留，逐项减少辅助材料，保持正式来源文本完整。
    while size(current) > max_chars:
        memory = current.memory
        if memory.recalled:
            current = current.model_copy(
                update={"memory": memory.model_copy(update={"recalled": memory.recalled[:-1]})}
            )
        elif memory.resident:
            current = current.model_copy(
                update={"memory": memory.model_copy(update={"resident": memory.resident[:-1]})}
            )
        elif memory.segment_summaries:
            current = current.model_copy(
                update={
                    "memory": memory.model_copy(
                        update={"segment_summaries": memory.segment_summaries[1:]}
                    )
                }
            )
        elif memory.session_digest:
            current = current.model_copy(
                update={"memory": memory.model_copy(update={"session_digest": ""})}
            )
        elif memory.state_summary:
            current = current.model_copy(
                update={"memory": memory.model_copy(update={"state_summary": ""})}
            )
        elif memory.core_memory:
            current = current.model_copy(
                update={"memory": memory.model_copy(update={"core_memory": ""})}
            )
        elif current.perspective.history:
            history = current.perspective.history[1:]
            ids = {item.message_id for item in history}
            current = current.model_copy(
                update={
                    "perspective": current.perspective.model_copy(update={"history": history}),
                    "memory": memory.model_copy(
                        update={
                            "history_thoughts": tuple(
                                item for item in memory.history_thoughts if item.message_id in ids
                            )
                        }
                    ),
                }
            )
        else:
            raise ContextBudgetExceeded(current)
    return current


class AutomaticMemory:
    def __init__(self, database: Database, retrieval: MemoryRetrieval) -> None:
        self.database, self.retrieval = database, retrieval

    def _next(self):
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT t.* FROM conversation_tasks t JOIN communities c USING(community_id) "
                "JOIN conversations v USING(conversation_id) "
                "WHERE t.status='pending' AND t.attempt_count=0 AND c.status='active' "
                "AND v.status='active' "
                "AND json_extract(t.snapshot_json,'$.memory.retrieval_prepared')=0 "
                "ORDER BY t.created_at_utc,t.task_id LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    async def run_once(self) -> bool:
        row = await asyncio.to_thread(self._next)
        if row is None:
            return False
        snapshot = ContextSnapshot.model_validate_json(row["snapshot_json"])
        scope = SearchScope(
            snapshot.scope.community_id,
            snapshot.scope.character_id,
            snapshot.prepared_at_utc,
            snapshot.scope.conversation_id,
            snapshot.scope.observation_upper_sequence,
        )
        version = next(
            item.version for item in snapshot.source_versions if item.kind == "memory_search"
        )
        try:
            hits = await self.retrieval.search_async(
                self.database,
                scope,
                snapshot.memory.retrieval_query,
                limit=self.retrieval.policy.automatic_limit,
                expected_source_version=version,
            )
        except ConflictError:
            hits = ()
        await asyncio.to_thread(self._finish, row, snapshot, scope, hits)
        return True

    def _finish(self, row, snapshot, scope, hits) -> None:
        with self.database.transaction() as connection:
            current = ConversationTaskRepository().get(connection, row["task_id"])
            if current["status"] != "pending" or current["snapshot_json"] != row["snapshot_json"]:
                return
            instance = InstanceRepository().get(connection, scope.community_id, scope.character_id)
            if instance.memory_status.value != "ready":
                return
            allowed = self.retrieval.sources(connection, scope)
            existing = {item.content for item in snapshot.memory.resident}
            existing.update(item.content for item in snapshot.memory.segment_summaries)
            existing.update(
                item.text for item in (*snapshot.perspective.history, *snapshot.perspective.inputs)
            )
            recalled, chars = [], 0
            for hit in hits:
                actual = allowed.get((hit.source_kind, hit.source_id))
                if (
                    actual is None
                    or actual.source_version != hit.source_version
                    or hit.text in existing
                ):
                    continue
                if chars + len(hit.text) > self.retrieval.policy.automatic_max_chars:
                    continue
                recalled.append(
                    MemoryItem(
                        memory_id=hit.source_id,
                        content_version=hit.source_version,
                        source_kind=hit.source_kind,
                        content=hit.text,
                        occurred_at_utc=hit.occurred_at_utc,
                    )
                )
                existing.add(hit.text)
                chars += len(hit.text)
            final = snapshot.model_copy(
                update={
                    "memory": snapshot.memory.model_copy(
                        update={"retrieval_prepared": True, "recalled": tuple(recalled)}
                    ),
                    "source_versions": snapshot.source_versions
                    + tuple(
                        SourceVersion(
                            kind=item.source_kind,
                            source_id=item.memory_id,
                            version=item.content_version,
                        )
                        for item in recalled
                    ),
                }
            )
            final = budget_snapshot(final, self.retrieval.policy.input_max_chars)
            connection.execute(
                "UPDATE conversation_tasks SET snapshot_json=?,updated_at_utc=? WHERE task_id=?",
                (final.model_dump_json(), datetime.now(UTC).isoformat(), row["task_id"]),
            )
