from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from echo_commons.agents.contracts.context import (
    ActionSpace,
    ContextSnapshot,
    EnvironmentContext,
    MemoryContext,
    MemoryItem,
    ObservedMessage,
    PerspectiveContext,
    RelationshipView,
    SelfContext,
    SnapshotScope,
    SourceVersion,
)
from echo_commons.agents.contracts.output import CHARACTER_MESSAGE_CONTRACT
from echo_commons.modules.characters.domain.relationship import RelationshipKey
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.domain.conversation import Membership
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval, SearchScope
from echo_commons.modules.perspective.contracts import ObservationScope
from echo_commons.modules.perspective.reader import WorldPerspective
from echo_commons.modules.social.domain import SocialTurn
from echo_commons.shared.actors import ActorRef


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    recent_message_limit: int
    recent_message_max_chars: int
    resident_memory_limit: int
    allowed_tools: frozenset[str]

    def __post_init__(self) -> None:
        if (
            min(
                self.recent_message_limit, self.recent_message_max_chars, self.resident_memory_limit
            )
            < 1
        ):
            raise ValueError("Context material limits must be positive")


class ConversationContext:
    def __init__(
        self,
        policy: ContextPolicy,
        catalog: BlueprintCatalog,
        communities: CommunityRepository,
        conversations: ConversationRepository,
        instances: InstanceRepository,
        states: StateRepository,
        relationships: RelationshipRepository,
        entries: MemoryEntryRepository,
        provenance: MemoryProvenanceRepository,
        perspective: WorldPerspective,
        retrieval: MemoryRetrieval,
        capabilities: CapabilityResolver,
    ) -> None:
        self.policy, self.catalog, self.communities, self.conversations = (
            policy,
            catalog,
            communities,
            conversations,
        )
        self.instances, self.states, self.relationships = instances, states, relationships
        self.entries, self.provenance, self.perspective, self.retrieval, self.capabilities = (
            entries,
            provenance,
            perspective,
            retrieval,
            capabilities,
        )

    def prepare(
        self,
        connection: sqlite3.Connection,
        turn: SocialTurn,
        member: Membership,
        inputs: tuple[Message, ...],
        now: datetime,
    ) -> ContextSnapshot:
        character_id = member.actor.actor_id
        instance = self.instances.get(connection, turn.community_id, character_id)
        blueprint = self.catalog.blueprint(instance.blueprint_id)
        if (
            blueprint.version != instance.blueprint_version
            or blueprint.voice is None
            or blueprint.relational_dynamics is None
        ):
            raise ValueError("The bound character blueprint is incomplete or unavailable")
        community = self.communities.get(connection, turn.community_id)
        conversation = self.conversations.get(connection, turn.community_id, turn.conversation_id)
        observation = self.perspective.observe(
            connection,
            ObservationScope(
                turn.community_id, turn.conversation_id, member.actor, turn.observation_max_sequence
            ),
        )
        input_ids = {message.message_id for message in inputs}
        history = []
        remaining = self.policy.recent_message_max_chars
        for message in reversed(observation.messages):
            if message.message_id in input_ids:
                continue
            if len(history) >= self.policy.recent_message_limit or len(message.text) > remaining:
                break
            history.append(message)
            remaining -= len(message.text)
        history.reverse()
        states = {
            kind: self.states.latest(connection, character_id, kind, now) for kind in StateKind
        }
        relations = []
        relation_versions = []
        targets = {participant.actor for participant in observation.participants}
        targets.update(message.sender for message in inputs + tuple(history))
        targets.update(
            ActorRef(key.target_kind.value, key.target_id)
            for key in self.relationships.keys(connection, turn.community_id, character_id)
        )
        for actor in sorted(targets, key=lambda actor: (actor.kind.value, actor.actor_id)):
            if actor == member.actor:
                continue
            state = self.relationships.get(
                connection,
                RelationshipKey(turn.community_id, character_id, actor.kind.value, actor.actor_id),
                now,
            )
            relations.append(
                RelationshipView(
                    target=actor,
                    target_name=self.perspective.actor_name(connection, turn.community_id, actor),
                    relationship_type=state.relationship_type.value,
                    attitude=state.attitude_summary,
                )
            )
            relation_versions.append(
                SourceVersion(
                    kind="relationship",
                    source_id=f"{character_id}/{actor.kind.value}/{actor.actor_id}",
                    version=str(state.state_version),
                )
            )
        resident = tuple(
            MemoryItem(
                memory_id=row["memory_id"],
                content_version=row["content_version"],
                content=row["content"],
            )
            for row in self.entries.active_rows(
                connection, turn.community_id, character_id, valid_at=now, recorded_before=now
            )
            if row["visibility"] == "resident"
        )[: self.policy.resident_memory_limit]
        digest = self.provenance.latest_digest(
            connection, turn.community_id, character_id, turn.conversation_id
        )
        tools = self.capabilities.tools(blueprint, self.policy.allowed_tools)
        versions = [
            SourceVersion(
                kind="blueprint", source_id=blueprint.resource_id, version=blueprint.version
            ),
            SourceVersion(
                kind="community", source_id=turn.community_id, version=str(community.state_version)
            ),
            SourceVersion(
                kind="memory_search",
                source_id=character_id,
                version=self.retrieval.source_version(
                    connection,
                    SearchScope(
                        turn.community_id,
                        character_id,
                        now,
                        turn.conversation_id,
                        turn.observation_max_sequence,
                    ),
                ),
            ),
        ]
        versions.extend(relation_versions)
        versions.append(
            SourceVersion(
                kind="conversation_membership",
                source_id=turn.conversation_id,
                version=str(turn.membership_version),
            )
        )
        versions.extend(
            SourceVersion(
                kind="identity_resource",
                source_id=resource.resource_id,
                version=resource.content_version,
            )
            for resource in (
                self.catalog.agent_contract,
                blueprint.profile,
                blueprint.voice,
                blueprint.relational_dynamics,
                blueprint.capabilities_resource,
            )
            if resource is not None
        )
        versions.extend(
            SourceVersion(kind="message", source_id=message.message_id, version="1")
            for message in inputs + tuple(history)
        )
        versions.extend(
            SourceVersion(
                kind="memory_entry", source_id=memory.memory_id, version=memory.content_version
            )
            for memory in resident
        )
        versions.extend(
            SourceVersion(
                kind="character_state", source_id=entry.entry_id, version=str(entry.state_version)
            )
            for entry in states.values()
            if entry
        )
        if digest:
            versions.append(
                SourceVersion(
                    kind="conversation_digest",
                    source_id=digest["digest_id"],
                    version=digest["content_version"],
                )
            )
        return ContextSnapshot(
            snapshot_id=str(uuid4()),
            prepared_at_utc=now,
            scope=SnapshotScope(
                community_id=turn.community_id,
                character_id=character_id,
                conversation_id=turn.conversation_id,
                membership_id=member.membership_id,
                observation_upper_sequence=turn.observation_max_sequence,
                social_turn_id=turn.social_turn_id,
            ),
            self=SelfContext(
                character_id=character_id,
                name=blueprint.display_name,
                blueprint_id=blueprint.resource_id,
                blueprint_version=blueprint.version,
                agent_contract=self.catalog.agent_contract.content,
                profile=blueprint.profile.content,
                voice=blueprint.voice.content,
                relational_dynamics=blueprint.relational_dynamics.content,
                mood=states[StateKind.MOOD].value if states[StateKind.MOOD] else "",
                physical_state=states[StateKind.PHYSICAL].value
                if states[StateKind.PHYSICAL]
                else "",
                activity=states[StateKind.ACTIVITY].value if states[StateKind.ACTIVITY] else "",
                relationships=tuple(relations),
                capabilities=tools,
            ),
            perspective=PerspectiveContext(
                inputs=tuple(self.message(connection, message) for message in inputs),
                history=tuple(self.message(connection, message) for message in history),
                public_facts=tuple(
                    f"{participant.actor.kind.value}:{participant.actor.actor_id} "
                    f"{participant.display_name}"
                    for participant in observation.participants
                ),
            ),
            memory=MemoryContext(
                resident=resident, session_digest=digest["content"] if digest else ""
            ),
            environment=EnvironmentContext(
                world_time_utc=community.world_time_utc,
                community_status=community.status.value,
                conversation_kind=conversation.kind.value,
            ),
            action_space=ActionSpace(output_contracts=(CHARACTER_MESSAGE_CONTRACT,), tools=tools),
            source_versions=tuple(versions),
        )

    def message(self, connection: sqlite3.Connection, message: Message) -> ObservedMessage:
        return ObservedMessage(
            message_id=message.message_id,
            sequence=message.sequence,
            sender=message.sender,
            sender_name=self.perspective.actor_name(
                connection, message.community_id, message.sender
            ),
            text=message.text,
            occurred_at_utc=message.created_at_utc,
            reply_to_message_id=message.reply_to_message_id,
        )
