import json
import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.domain.changes import RelationshipChange, StateChange
from echo_commons.modules.characters.domain.relationship import (
    RelationshipEvidence,
    RelationshipEvidenceKind,
    RelationshipImpact,
    RelationshipKey,
    RelationshipPolicy,
    RelationshipValues,
    apply_relationship_evidence,
)
from echo_commons.modules.characters.domain.state import StateEntry, StateKind
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.memory.contracts import MemoryChangeWriter
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError


def reflection_relationship_policy() -> RelationshipPolicy:
    return RelationshipPolicy(
        RelationshipValues(50, 50, 0),
        60,
        60,
        frozenset(RelationshipEvidenceKind),
        frozenset({RelationshipEvidenceKind.SUPPORT, RelationshipEvidenceKind.COMMITMENT}),
        frozenset({RelationshipEvidenceKind.SUPPORT, RelationshipEvidenceKind.COMMITMENT}),
    )


class CharacterFacts:
    def refresh_attitude(
        self, connection, community_id, character_id, target, content, observed_at, now
    ):
        evidence_ids = tuple(
            row[0]
            for row in connection.execute(
                "SELECT evidence_id FROM relation_evidence WHERE community_id=? "
                "AND observer_character_id=? AND target_kind=? AND target_id=? "
                "AND recorded_at_utc<=? ORDER BY recorded_at_utc DESC,evidence_id LIMIT 64",
                (
                    community_id,
                    character_id,
                    target.kind.value,
                    target.actor_id,
                    utc_text(observed_at),
                ),
            )
        )
        if not evidence_ids:
            raise ConflictError("Relationship view has no recorded evidence")
        cursor = connection.execute(
            "UPDATE relationship_state SET attitude_summary=?,attitude_source_refs_json=?,"
            "updated_at_utc=? WHERE community_id=? AND observer_character_id=? "
            "AND target_kind=? AND target_id=? AND relationship_type!='stranger'",
            (
                content,
                json.dumps(evidence_ids),
                utc_text(now),
                community_id,
                character_id,
                target.kind.value,
                target.actor_id,
            ),
        )
        if not cursor.rowcount:
            raise ConflictError("Relationship view target is unavailable")

    def __init__(
        self,
        instances: InstanceReader,
        relationships: RelationshipRepository,
        states: StateRepository,
        policy: RelationshipPolicy,
        communities: CommunityReader,
        changes: MemoryChangeWriter | None = None,
    ) -> None:
        self.instances, self.relationships, self.states, self.policy = (
            instances,
            relationships,
            states,
            policy,
        )
        self.communities = communities
        self.changes = changes

    def apply(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        source_kind: str,
        source_ref: str,
        relationships: tuple[RelationshipChange, ...],
        states: tuple[StateChange, ...],
        now: datetime,
    ) -> None:
        self.instances.get(connection, community_id, character_id)
        identities = [(item.target, item.dimension) for item in relationships]
        if len(identities) != len(set(identities)):
            raise ConflictError("Relationship changes repeat a target and dimension")
        if len({item.kind for item in states}) != len(states):
            raise ConflictError("State changes repeat a state kind")
        for target in dict.fromkeys(item.target for item in relationships):
            self.communities.require_member(connection, community_id, target)
            if target == ActorRef("character", character_id):
                raise ConflictError("Relationship changes require another actor")
            key = RelationshipKey(community_id, character_id, target.kind.value, target.actor_id)
            changes = tuple(item for item in relationships if item.target == target)
            if len({item.evidence_kind for item in changes}) != 1:
                raise ConflictError("One relationship event must use one evidence category")
            if self.relationships.evidence(connection, key, source_kind, source_ref) is not None:
                continue
            evidence = RelationshipEvidence(
                uuid4(),
                key,
                changes[0].evidence_kind,
                source_kind,
                source_ref,
                max(item.occurred_at for item in changes),
                now,
            )
            current = self.relationships.get(connection, key, now)
            transition = apply_relationship_evidence(
                current,
                evidence,
                tuple(
                    RelationshipImpact(
                        evidence.evidence_id, item.dimension, item.direction, item.magnitude
                    )
                    for item in changes
                ),
                self.policy,
                expected_version=current.state_version,
                updated_at_utc=now,
            )
            self.relationships.add_evidence(connection, evidence)
            if transition.state_changed:
                self.relationships.save(connection, transition.state)
                if self.changes:
                    self.changes.record(
                        connection,
                        community_id,
                        character_id,
                        "relationship",
                        f"{character_id}/{target.kind.value}/{target.actor_id}",
                        transition.state.state_version,
                        now,
                    )
        for change in states:
            value = change.value.strip()
            if not value:
                raise ConflictError("State value must not be blank")
            existing = connection.execute(
                "SELECT value FROM character_state_entries WHERE character_id = ? "
                "AND state_kind = ? AND source_kind = ? AND source_ref = ?",
                (character_id, change.kind.value, source_kind, source_ref),
            ).fetchone()
            if existing is not None:
                if existing[0] != value:
                    raise ConflictError("State source already records another value")
                continue
            version = connection.execute(
                "SELECT COALESCE(MAX(state_version), 0) FROM character_state_entries "
                "WHERE character_id = ? AND state_kind = ?",
                (character_id, change.kind.value),
            ).fetchone()[0]
            entry_id = str(uuid4())
            self.states.add(
                connection,
                StateEntry(
                    entry_id,
                    community_id,
                    character_id,
                    change.kind,
                    value,
                    source_kind,
                    source_ref,
                    version + 1,
                    now,
                    now + timedelta(hours=24) if change.kind is StateKind.ACTIVITY else None,
                ),
            )
            if self.changes:
                self.changes.record(
                    connection,
                    community_id,
                    character_id,
                    "character_state",
                    entry_id,
                    version + 1,
                    now,
                )
