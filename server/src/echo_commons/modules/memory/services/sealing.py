from datetime import UTC, datetime

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.memory.domain.sources import MemorySource, SourceKind
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.perspective.contracts import WorldReader
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError


class MemorySealing:
    def __init__(
        self,
        database: Database,
        instances: InstanceReader,
        conversations: ConversationReader,
        perspective: WorldReader,
        segments: SegmentRepository,
        thoughts: ThoughtRepository,
        *,
        max_messages=100,
        max_materials=256,
        max_material_chars=20000,
        idle_seconds=600,
    ):
        self.database, self.instances, self.conversations = database, instances, conversations
        self.perspective, self.segments, self.thoughts = perspective, segments, thoughts
        self.max_messages, self.max_materials, self.max_material_chars = (
            max_messages,
            max_materials,
            max_material_chars,
        )
        self.idle_seconds = idle_seconds

    def seal(self, community_id, character_id, *, observed_at=None):
        with self.database.transaction() as connection:
            return self.freeze(connection, community_id, character_id, observed_at=observed_at)

    def pending(self, connection, community_id, character_id, now):
        actor = ActorRef("character", character_id)
        boundaries = self.perspective.freeze(connection, community_id, actor, now)
        visible = self.perspective.experiences(connection, community_id, actor, boundaries, now)
        covered = self.segments.covered_messages(connection, community_id, character_id)
        messages = tuple(m for m in visible if m.message_id not in covered)
        thoughts = self.thoughts.for_results(
            connection,
            community_id,
            character_id,
            tuple(m.result_id for m in visible if m.result_id and m.sender == actor),
            now,
        )
        return messages, thoughts, boundaries, visible

    def freeze(
        self,
        connection,
        community_id,
        character_id,
        *,
        observed_at=None,
        idle_seconds=None,
        automatic=False,
        message_ids=None,
        boundaries=None,
    ):
        now = observed_at or datetime.now(UTC)
        idle_seconds = idle_seconds if idle_seconds is not None else self.idle_seconds
        self.instances.get(connection, community_id, character_id)
        messages, thoughts, available_boundaries, visible = self.pending(
            connection, community_id, character_id, now
        )
        boundaries = available_boundaries if boundaries is None else boundaries
        if message_ids is not None:
            messages = tuple(m for m in messages if m.message_id in message_ids)
        if not messages:
            return None
        scenes = []
        for boundary in boundaries:
            for member in self.conversations.members(
                connection, boundary.conversation_id, current_only=False
            ):
                if member.membership_id not in boundary.membership_ids:
                    continue
                scoped = tuple(
                    m
                    for m in messages
                    if m.conversation_id == boundary.conversation_id
                    and m.sequence <= boundary.upper_sequence
                    and member.covers(m.sequence)
                )
                if scoped:
                    scenes.append(
                        (
                            scoped,
                            boundary.model_copy(
                                update={
                                    "membership_ids": (member.membership_id,),
                                }
                            ),
                            tuple(
                                m
                                for m in visible
                                if m.conversation_id == boundary.conversation_id
                                and member.covers(m.sequence)
                            ),
                        )
                    )
        for scoped, boundary, scene_visible in sorted(
            scenes, key=lambda item: item[0][0].created_at_utc
        ):
            segment = self._freeze_scene(
                connection,
                community_id,
                character_id,
                now,
                idle_seconds,
                automatic,
                scoped,
                thoughts,
                (boundary,),
                scene_visible,
            )
            if segment is not None:
                return segment
        return None

    def _freeze_scene(
        self,
        connection,
        community_id,
        character_id,
        now,
        idle_seconds,
        automatic,
        messages,
        thoughts,
        boundaries,
        visible,
    ):
        selected, sources, chars = [], [], 0
        endings = []
        actor = ActorRef("character", character_id)
        for scene in boundaries:
            conversation = self.conversations.get(connection, community_id, scene.conversation_id)
            if conversation.status.value == "archived":
                endings.append(conversation.updated_at_utc)
            endings.extend(
                member.left_at_utc
                for member in self.conversations.members(
                    connection, scene.conversation_id, current_only=False
                )
                if member.actor == actor
                and member.left_at_utc is not None
                and member.membership_id in scene.membership_ids
            )
        ending = min(
            (value for value in endings if messages[0].created_at_utc <= value <= now),
            default=None,
        )
        context = []
        closed = False
        for message in messages:
            if ending is not None and message.created_at_utc > ending:
                closed = True
                break
            if (
                selected
                and (message.created_at_utc - selected[-1].created_at_utc).total_seconds()
                >= idle_seconds
            ):
                closed = True
                break
            thought = thoughts.get(message.result_id)
            count = 2 if thought else 1
            size = len(message.text) + (len(thought["content"]) if thought else 0)
            proposed_context, context_chars = self.context(
                (*selected, message), visible, thoughts, idle_seconds
            )
            if (
                len(selected) >= self.max_messages
                or len(sources) + count + len(proposed_context) > self.max_materials
                or chars + size + context_chars > self.max_material_chars
            ):
                if not selected:
                    raise ConflictError("One memory event exceeds the configured material budget")
                closed = True
                break
            selected.append(message)
            sources.append(MemorySource(SourceKind.MESSAGE, message.message_id, "1"))
            if thought:
                sources.append(
                    MemorySource(
                        SourceKind.THOUGHT, thought["thought_id"], thought["content_version"]
                    )
                )
            chars += size
            context = proposed_context
        closed = closed or len(selected) >= self.max_messages or len(sources) >= self.max_materials
        closed = closed or chars >= self.max_material_chars
        closed = closed or (now - selected[-1].created_at_utc).total_seconds() >= idle_seconds
        closed = closed or ending is not None
        if automatic and not closed:
            return None
        return self.segments.add(
            connection,
            community_id,
            character_id,
            tuple(selected),
            tuple(sources),
            boundaries,
            tuple(context),
            now,
        )

    def context(self, selected, visible, thoughts, idle_seconds):
        new_ids = {m.message_id for m in selected}
        context, chars = [], 0
        first = selected[0]
        first_thought = thoughts.get(first.result_id)
        first_size = len(first.text) + (len(first_thought["content"]) if first_thought else 0)
        char_budget = min(self.max_material_chars // 5, self.max_material_chars - first_size)
        count_budget = min(
            self.max_materials // 5, self.max_materials - (2 if first_thought else 1)
        )
        # 为继续交流预留前情容量，优先直接回复和上一条发言。
        for conversation_id in dict.fromkeys(m.conversation_id for m in selected):
            upcoming = tuple(m for m in selected if m.conversation_id == conversation_id)
            if not upcoming:
                continue
            before = tuple(
                m
                for m in visible
                if m.conversation_id == conversation_id
                and m.sequence < upcoming[0].sequence
                and m.message_id not in new_ids
            )
            reply_ids = {m.reply_to_message_id for m in upcoming if m.reply_to_message_id}
            chosen = {m.message_id: m for m in before if m.message_id in reply_ids}
            chosen.update(
                (m.message_id, m)
                for m in reversed(before[-4:])
                if (upcoming[0].created_at_utc - m.created_at_utc).total_seconds() < idle_seconds
            )
            for index, message in enumerate(chosen.values()):
                thought = thoughts.get(message.result_id)
                size = len(message.text) + (len(thought["content"]) if thought else 0)
                count = 2 if thought else 1
                if index == 0:
                    char_budget = min(
                        self.max_material_chars - first_size, max(char_budget, chars + size)
                    )
                    count_budget = min(
                        self.max_materials - (2 if first_thought else 1),
                        max(count_budget, len(context) + count),
                    )
                if chars + size > char_budget or len(context) + count > count_budget:
                    continue
                context.append(MemorySource(SourceKind.MESSAGE, message.message_id, "1"))
                if thought:
                    context.append(
                        MemorySource(
                            SourceKind.THOUGHT, thought["thought_id"], thought["content_version"]
                        )
                    )
                chars += size
        return context, chars
