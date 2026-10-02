from datetime import UTC, datetime

from test_message_perspective import build_system, send

from echo_commons.modules.characters.domain.changes import RelationshipChange, StateChange
from echo_commons.modules.characters.domain.relationship import (
    RelationshipDimension,
    RelationshipDirection,
)
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.facts import (
    CharacterFacts,
    reflection_relationship_policy,
)
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.actors import ActorRef


def test_character_fact_targets_and_source_deduplication_use_real_transaction(tmp_path):
    system = build_system(tmp_path)
    message = send(system, "谢谢大家一起帮忙", mentions=(ActorRef("character", "second"),))
    service = CharacterFacts(
        InstanceRepository(),
        RelationshipRepository(),
        StateRepository(),
        reflection_relationship_policy(),
        CommunityRepository(),
    )
    now = datetime.now(UTC)
    changes = tuple(
        RelationshipChange(actor, RelationshipDimension.TRUST, RelationshipDirection.UP, 2, now)
        for actor in (ActorRef("player", "alice"), ActorRef("character", "second"))
    )
    for _ in range(2):
        with system.database.transaction() as connection:
            service.apply(
                connection,
                "community",
                "first",
                "message",
                message.message_id,
                changes,
                (StateChange(StateKind.MOOD, "受到帮助后的安心"),),
                now,
            )
    with system.database.read() as connection:
        evidence = connection.execute(
            "SELECT target_kind,target_id FROM relation_evidence ORDER BY target_kind"
        ).fetchall()
        assert tuple(tuple(row) for row in evidence) == (
            ("character", "second"),
            ("player", "alice"),
        )
        assert connection.execute("SELECT COUNT(*) FROM relationship_state").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM character_state_entries WHERE source_ref = ?",
                (message.message_id,),
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
