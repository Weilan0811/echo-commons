from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.domain.instance import AvailabilityStatus
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.communities.domain import CommunityStatus
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.domain.conversation import ConversationStatus
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.input_batches import InputBatchRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.tasks.context import ConversationContext
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.domain import (
    ParticipationDecision,
    ParticipationStatus,
    SocialTurn,
    TurnStatus,
)
from echo_commons.modules.social.participation import Candidate, choose
from echo_commons.modules.social.repository import SocialRepository
from echo_commons.shared.actors import ActorKind


class TurnPlanner:
    def __init__(
        self,
        database: Database,
        communities: CommunityRepository,
        conversations: ConversationRepository,
        instances: InstanceRepository,
        messages: MessageRepository,
        batches: InputBatchRepository,
        social: SocialRepository,
        tasks: ConversationTaskRepository,
        perspective: PerspectiveReader,
        context: ConversationContext,
        completion: TurnCompletion,
        *,
        maximum_responders: int = 2,
    ) -> None:
        self.database, self.communities, self.conversations, self.instances = (
            database,
            communities,
            conversations,
            instances,
        )
        self.messages, self.batches, self.social, self.tasks = messages, batches, social, tasks
        self.perspective, self.context, self.completion, self.maximum_responders = (
            perspective,
            context,
            completion,
            maximum_responders,
        )

    def plan(self) -> tuple[str, ...]:
        with self.database.transaction() as connection:
            self.batches.seal_due(connection, datetime.now(UTC))
        with self.database.read() as connection:
            scopes = dict.fromkeys(
                (
                    batch["community_id"],
                    batch["conversation_id"],
                    batch["visibility"],
                    batch["audience_json"],
                )
                for batch in self.batches.awaiting(connection)
            )
        created = []
        for scope in scopes:
            with self.database.transaction() as connection:
                turn_id = self._plan_group(connection, scope)
                if turn_id is not None:
                    created.append(turn_id)
        return tuple(created)

    def _plan_group(
        self, connection: sqlite3.Connection, scope: tuple[str, str, str, str]
    ) -> str | None:
        community_id, conversation_id, visibility, audience_json = scope
        batches = self.batches.awaiting(connection, scope=scope)
        if not batches:
            return None
        now = datetime.now(UTC)
        community = self.communities.get(connection, community_id)
        conversation = self.conversations.get(connection, community_id, conversation_id)
        if (
            community.status is CommunityStatus.PAUSED
            or conversation.status is ConversationStatus.ARCHIVED
            or self.social.running(connection, conversation_id)
        ):
            return None
        source_ids = tuple(
            identity
            for batch in batches
            for identity in self.batches.message_ids(connection, batch["input_batch_id"])
        )
        inputs = tuple(
            sorted(
                (
                    self.messages.get(connection, conversation_id, identity)
                    for identity in source_ids
                ),
                key=lambda message: message.sequence,
            )
        )
        if not inputs:
            raise ValueError("Sealed input batch has no messages")
        audience = tuple(json.loads(audience_json))
        if any(
            message.audience != audience or message.visibility.value != visibility
            for message in inputs
        ):
            raise ValueError("Input batch sources disagree with their audience")
        turn = SocialTurn(
            str(uuid4()),
            community_id,
            conversation_id,
            audience,
            visibility,
            conversation.next_sequence - 1,
            conversation.membership_version,
            TurnStatus.RUNNING,
            now,
            None,
        )
        self.social.add(connection, turn, tuple(batch["input_batch_id"] for batch in batches))
        members = self.conversations.members(connection, conversation_id, current_only=False)
        by_actor = {member.actor: member for member in members}
        current = {member.actor: member for member in members if member.left_at_utc is None}
        candidates = []
        mentions = {actor for message in inputs for actor in message.mentions}
        for actor in by_actor:
            if actor.kind is not ActorKind.CHARACTER:
                continue
            member = current.get(actor)
            instance = self.instances.get(connection, community_id, actor.actor_id)
            reason = None
            if member is None:
                reason = "member_left"
            elif member.membership_id not in audience:
                reason = "outside_audience"
            elif instance.availability_status is not AvailabilityStatus.AVAILABLE:
                reason = "unavailable"
            else:
                scope = ObservationScope(
                    community_id,
                    conversation_id,
                    actor,
                    turn.observation_max_sequence,
                    member.membership_id,
                )
                if not all(
                    self.perspective.visible(connection, scope, message) for message in inputs
                ):
                    reason = "source_not_visible"
            candidates.append(
                Candidate(
                    actor.actor_id,
                    actor in mentions,
                    self.messages.last_spoke(connection, conversation_id, actor.actor_id),
                    reason,
                )
            )
        selected = choose(
            tuple(candidates),
            1 if conversation.kind.value == "direct" else self.maximum_responders,
        )
        for candidate in candidates:
            chosen = candidate.character_id in selected
            reason = (
                "mentioned"
                if chosen and candidate.mentioned
                else "rotation"
                if chosen
                else candidate.exclusion_reason or "responder_limit"
            )
            self.social.decision(
                connection,
                ParticipationDecision(
                    turn.social_turn_id,
                    candidate.character_id,
                    reason,
                    selected.index(candidate.character_id) if chosen else None,
                    ParticipationStatus.SELECTED if chosen else ParticipationStatus.SILENT,
                    None if chosen else "silent",
                    now,
                ),
            )
            if chosen:
                member = next(
                    member
                    for actor, member in current.items()
                    if actor.actor_id == candidate.character_id
                    and actor.kind is ActorKind.CHARACTER
                )
                snapshot = self.context.prepare(connection, turn, member, inputs, now)
                self.tasks.prepare(connection, snapshot)
        self.completion.update(connection, turn.social_turn_id, now)
        return turn.social_turn_id
