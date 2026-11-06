import json
import sqlite3
from uuid import uuid4

from echo_commons.agents.contracts.activity import (
    PREPARATION_ADAPTER,
    ActivityScope,
    IntentProposal,
    WorkingIntent,
    WorkingMemory,
)
from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.activities.observation import GameObservationService
from echo_commons.modules.activities.repositories.inputs import ActivityInputRepository
from echo_commons.modules.activities.repositories.working_memory import WorkingMemoryRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, IdempotencyConflict, NotFoundError


class ActivityWorkingMemory:
    def __init__(
        self,
        database: Database,
        observations: GameObservationService,
        conversations: ConversationRepository,
    ) -> None:
        self.database, self.observations, self.conversations = database, observations, conversations
        self.repository = WorkingMemoryRepository()
        self.inputs = ActivityInputRepository()

    def current_in(self, connection: sqlite3.Connection, scope: ActivityScope) -> WorkingMemory:
        try:
            context = self.observations.participation.participant_context(
                connection,
                scope.community_id,
                ActorRef("character", scope.character_id),
                scope.game_id,
                scope.participation_id,
            )
        except NotFoundError:
            return WorkingMemory()
        conversation = self.conversations.get(connection, scope.community_id, scope.conversation_id)
        if context.game.status != "running" or conversation.status != "active":
            return WorkingMemory()
        return self.repository.read(connection, scope)

    def replace(
        self,
        community_id: str,
        character_id: str,
        input_id: str,
        *,
        expected_version: int,
        intents: tuple[IntentProposal, ...],
    ) -> WorkingMemory:
        with self.database.transaction() as connection:
            return self.replace_in(
                connection,
                community_id,
                character_id,
                input_id,
                expected_version=expected_version,
                intents=intents,
            )

    def replace_in(
        self,
        connection,
        community_id: str,
        character_id: str,
        input_id: str,
        *,
        expected_version: int,
        intents: tuple[IntentProposal, ...],
    ) -> WorkingMemory:
        row = self.inputs.get(connection, community_id, character_id, input_id)
        if row["snapshot_json"] is None:
            raise ConflictError("Only a complete frozen input can update working memory")
        preparation = PREPARATION_ADAPTER.validate_json(row["preparation_json"])
        scope = preparation.scope
        context = self.observations.participation.participant_context(
            connection,
            community_id,
            ActorRef("character", character_id),
            scope.game_id,
            scope.participation_id,
        )
        conversation = self.conversations.get(connection, community_id, scope.conversation_id)
        if context.game.status != "running" or conversation.status != "active":
            self.repository.clear(connection, scope)
            return WorkingMemory()
        current = self.current_in(connection, scope)
        if current.last_input_id == input_id:
            old = tuple(
                IntentProposal(content=i.content, message_ids=i.message_ids)
                for i in current.intents
            )
            if old != intents:
                raise IdempotencyConflict("The same activity decision already updated its intents")
            return current
        if (
            current.version != expected_version
            or expected_version != preparation.evidence.working_memory.version
        ):
            raise ConflictError("The activity working memory changed after input preparation")
        common = json.loads(row["snapshot_json"])["material"]["conversation"]
        messages = {
            m["message_id"]
            for m in (*common["perspective"]["inputs"], *common["perspective"]["history"])
            if m["conversation_id"] == scope.conversation_id
        }
        previous = {i.content: i for i in current.intents}
        updated = []
        for proposal in intents:
            if not proposal.content.strip() or not set(proposal.message_ids) <= messages:
                raise ValueError(
                    "Intent requires meaningful content and visible message references"
                )
            old = previous.get(proposal.content)
            updated.append(
                old
                if old is not None and old.message_ids == proposal.message_ids
                else WorkingIntent(
                    **proposal.model_dump(),
                    intent_id=str(uuid4()),
                    source_input_id=input_id,
                )
            )
        value = WorkingMemory(
            version=current.version + 1, intents=tuple(updated), last_input_id=input_id
        )
        self.repository.save(connection, scope, value)
        return value

    def clear_in(self, connection: sqlite3.Connection, scope: ActivityScope) -> None:
        self.repository.clear(connection, scope)

    def expression_in(self, connection, snapshot, intents):
        scope = snapshot.scope
        context = self.observations.participation.participant_context(
            connection,
            scope.community_id,
            ActorRef("character", scope.character_id),
            scope.game_id,
            scope.participation_id,
        )
        if context.game.status != "running":
            return
        current = self.current_in(connection, scope)
        if current.version != snapshot.material.working_memory.version:
            raise ConflictError("Activity intentions changed during expression")
        messages = {m.message_id for m in snapshot.material.conversation.current_messages}
        if any(not i.content.strip() or not set(i.message_ids) <= messages for i in intents):
            raise ValueError("Expression intent references an unavailable message")
        value = WorkingMemory(
            version=current.version + 1,
            last_input_id=snapshot.origin_input_id,
            intents=tuple(
                WorkingIntent(
                    **i.model_dump(),
                    intent_id=str(uuid4()),
                    source_input_id=snapshot.origin_input_id,
                )
                for i in intents
            ),
        )
        self.repository.save(connection, scope, value)
