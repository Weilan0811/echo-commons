from __future__ import annotations

from datetime import datetime

import aiosqlite

from echo_commons.agents.contracts import (
    PROMPT_LAYOUT_VERSION,
    AgentMessage,
    CapabilityDefinition,
    CapabilityView,
    ContextRequest,
    ContextSnapshotV2,
    ConversationContinuity,
    IdentityContext,
    MemoryAccessPolicy,
    SnapshotSourceVersion,
)
from echo_commons.domain.input_batch import InputBatchStatus
from echo_commons.domain.messages import Message, SenderType
from echo_commons.domain.task import ConversationTask
from echo_commons.services.context.source import ContextSnapshotSource, EmptyContextSource
from echo_commons.services.identity import IdentityCatalog, load_identity_catalog
from echo_commons.store.memory_repositories import ThoughtRepository
from echo_commons.store.runtime_repositories import (
    InputBatchRepository,
    RuntimeConversationRepository,
    RuntimeMessageRepository,
)


def _to_agent_message(message: Message, *, thought: str | None = None) -> AgentMessage:
    return AgentMessage(
        message_id=message.message_id,
        message_sequence=message.message_sequence,
        sender_type=message.sender.type.value,
        sender_id=message.sender.id,
        text=message.text,
        thought=thought,
        images=message.images,
        server_timestamp_utc=message.server_timestamp_utc,
        reply_to_message_id=message.reply_to_message_id,
    )


class ContextSnapshotBuilder:
    """Project a frozen ConversationTask into an immutable Agent context."""

    def __init__(
        self,
        messages: RuntimeMessageRepository,
        conversations: RuntimeConversationRepository,
        input_batches: InputBatchRepository,
        identity_catalog: IdentityCatalog | None = None,
        context_source: ContextSnapshotSource | None = None,
        *,
        thoughts: ThoughtRepository,
    ) -> None:
        self.messages = messages
        self.conversations = conversations
        self.input_batches = input_batches
        self.identity_catalog = identity_catalog or load_identity_catalog()
        self.context_source = context_source or EmptyContextSource()
        self.thoughts = thoughts

    async def build(
        self,
        task: ConversationTask,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection,
        recent_limit: int = 20,
        recent_max_chars: int = 6000,
        covered_overlap: int = 4,
        memory_search_max_results: int = 5,
        allow_memory_search: bool = False,
    ) -> ContextSnapshotV2:
        conversation = await self.conversations.get(
            task.account_id,
            task.conversation_id,
            connection=connection,
        )
        if conversation is None:
            raise LookupError("conversation_not_found")
        if conversation.context_version != task.context_version:
            raise LookupError("context_expired")
        batches = await self.input_batches.list_for_task(task.task_id, connection=connection)
        if not batches:
            raise LookupError("task_input_batches_not_found")
        if any(batch.status is not InputBatchStatus.ASSIGNED for batch in batches):
            raise LookupError("task_input_batches_not_assigned")

        input_messages = await self.messages.list_for_input_batches(
            task.account_id,
            task.conversation_id,
            tuple(batch.input_batch_id for batch in batches),
            connection=connection,
        )
        if not input_messages:
            raise LookupError("task_input_messages_not_found")
        if input_messages[-1].message_sequence != task.input_max_message_sequence:
            raise LookupError("task_input_boundary_mismatch")

        baseline = self.identity_catalog.default_baseline
        identity = self.identity_catalog.character(task.character_id)
        input_message_ids = tuple(message.message_id for message in input_messages)
        recent_messages = await self.messages.list_conversation_through(
            task.account_id,
            task.conversation_id,
            task.context_max_message_sequence,
            limit=recent_limit,
            exclude_message_ids=input_message_ids,
            connection=connection,
        )
        thoughts = await self.thoughts.list_for_results(
            tuple(
                dict.fromkeys(
                    message.result_id
                    for message in recent_messages
                    if message.sender.type is SenderType.CHARACTER
                    and message.sender.id == task.character_id
                    and message.result_id is not None
                )
            ),
            connection=connection,
        )
        thoughts_by_result = {thought.result_id: thought.content for thought in thoughts}
        source_snapshot = await self.context_source.load(
            task,
            now_utc=now_utc,
            connection=connection,
        )
        load_continuity = getattr(self.context_source, "load_continuity", None)
        if callable(load_continuity):
            digest, summaries = await load_continuity(
                task,
                through_sequence=min(
                    task.context_max_message_sequence, input_messages[0].message_sequence - 1
                ),
                connection=connection,
            )
            source_snapshot = source_snapshot.model_copy(
                update={"session_digest": digest, "segment_summaries": summaries}
            )
        # Keep a small original-wording tail even when summaries cover it.
        digest = source_snapshot.session_digest
        summaries = source_snapshot.segment_summaries

        def covered(sequence: int) -> bool:
            return bool(digest and sequence <= digest.covers_through_sequence) or any(
                s.first_message_sequence <= sequence <= s.last_message_sequence for s in summaries
            )

        overlap = 0
        chars = 0
        retained = []
        for message in reversed(recent_messages):
            if covered(message.message_sequence):
                if overlap >= covered_overlap:
                    continue
                overlap += 1
            thought = thoughts_by_result.get(message.result_id)
            thought_chars = len(thought) if thought is not None else 0
            if chars + len(message.text) + thought_chars > recent_max_chars:
                break
            chars += len(message.text) + thought_chars
            retained.append(message)
        recent_messages = tuple(reversed(retained))
        memory_context = source_snapshot.memory_context
        if allow_memory_search:
            memory_context = memory_context.model_copy(
                update={
                    "access_policy": MemoryAccessPolicy(
                        expected_source_version=await self._search_version(
                            task, now_utc, connection
                        ),
                        frozen_conversation_id=task.conversation_id,
                        frozen_max_sequence=task.context_max_message_sequence,
                        search_enabled=True,
                        search_tool_name="memory_search",
                        max_results=memory_search_max_results,
                        guidance="需要回想过去时，可以调用 memory_search；结果只是记忆线索。",
                    )
                }
            )
        profile = identity.profile
        voice = identity.voice
        relational_dynamics = identity.relational_dynamics
        capability_definitions = tuple(
            CapabilityDefinition(
                name=capability.name,
                description=capability.description,
                parameters=dict(capability.parameters),
                action_kind=capability.action_kind,
            )
            for capability in sorted(identity.capabilities, key=lambda item: item.name)
        )
        source_versions = (
            SnapshotSourceVersion(source="conversation", version=task.context_version),
            SnapshotSourceVersion(source="identity.bundle", version=identity.content_version),
            SnapshotSourceVersion(source="identity.profile", version=profile.content_version),
            *(
                (
                    SnapshotSourceVersion(
                        source="identity.voice",
                        version=voice.content_version,
                    ),
                )
                if voice is not None
                else ()
            ),
            *(
                (
                    SnapshotSourceVersion(
                        source="identity.relational_dynamics",
                        version=relational_dynamics.content_version,
                    ),
                )
                if relational_dynamics is not None
                else ()
            ),
            *(
                (
                    SnapshotSourceVersion(
                        source="identity.capabilities",
                        version=identity.capabilities_resource.content_version,
                    ),
                )
                if identity.capabilities_resource is not None
                else ()
            ),
            *source_snapshot.source_versions,
            *(
                (
                    SnapshotSourceVersion(
                        source="memory_search",
                        version=memory_context.access_policy.expected_source_version,
                    ),
                )
                if memory_context.access_policy.expected_source_version
                else ()
            ),
            *(
                SnapshotSourceVersion(
                    source=f"segment_summary:{s.segment_id}", version=s.content_version
                )
                for s in summaries
            ),
            *(
                (
                    SnapshotSourceVersion(
                        source="conversation_digest", version=digest.content_version
                    ),
                )
                if digest
                else ()
            ),
        )
        agent_input_messages = tuple(_to_agent_message(message) for message in input_messages)
        agent_recent_messages = tuple(
            _to_agent_message(message, thought=thoughts_by_result.get(message.result_id))
            for message in recent_messages
        )
        return ContextSnapshotV2(
            conversation_id=task.conversation_id,
            character_id=task.character_id,
            context_version=task.context_version,
            now_utc=now_utc,
            request=ContextRequest(
                conversation_id=task.conversation_id,
                character_id=task.character_id,
                trigger_message=agent_input_messages[-1],
                input_messages=agent_input_messages,
            ),
            identity=IdentityContext(
                contract_resource_id=baseline.resource_id,
                contract_content=baseline.content,
                contract_version=baseline.content_version,
                character_id=identity.resource_id,
                bundle_version=identity.content_version,
                profile_resource_id=profile.resource_id,
                profile_content=profile.content,
                profile_version=profile.content_version,
                voice_resource_id=voice.resource_id if voice is not None else None,
                voice_content=voice.content if voice is not None else "",
                voice_version=voice.content_version if voice is not None else None,
                relational_dynamics_resource_id=(
                    relational_dynamics.resource_id if relational_dynamics is not None else None
                ),
                relational_dynamics_content=(
                    relational_dynamics.content if relational_dynamics is not None else ""
                ),
                relational_dynamics_version=(
                    relational_dynamics.content_version if relational_dynamics is not None else None
                ),
            ),
            character_state=source_snapshot.character_state,
            relationship_state=source_snapshot.relationship_state,
            memory_context=memory_context,
            conversation_continuity=ConversationContinuity(
                session_digest=source_snapshot.session_digest,
                segment_summaries=summaries,
                active_threads=tuple(source_snapshot.active_threads),
                recent_tail=agent_recent_messages,
                raw_tail_limit=recent_limit,
            ),
            situation=source_snapshot.situation,
            capability_view=CapabilityView(
                available=capability_definitions,
            ),
            source_versions=source_versions,
            prompt_layout_version=PROMPT_LAYOUT_VERSION,
        )

    async def _search_version(
        self, task: ConversationTask, now_utc: datetime, connection: aiosqlite.Connection
    ) -> str:
        from echo_commons.services.memory.retrieval import MemorySearchScope, MemorySearchService

        return await MemorySearchService(self.messages.database).source_version(
            MemorySearchScope(task.account_id, task.character_id),
            now_utc=now_utc,
            frozen_conversation_id=task.conversation_id,
            frozen_max_sequence=task.context_max_message_sequence,
            connection=connection,
        )
