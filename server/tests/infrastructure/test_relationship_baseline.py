from datetime import UTC, datetime
from uuid import uuid4

import pytest

from echo_commons.modules.characters.domain.relationship import (
    RelationshipDimension,
    RelationshipDirection,
    RelationshipEvidence,
    RelationshipEvidenceKind,
    RelationshipImpact,
    RelationshipKey,
    RelationshipPolicy,
    RelationshipState,
    RelationshipValues,
    apply_relationship_evidence,
)
from echo_commons.shared.validation import DomainInvariantError


def test_relationship_math_uses_explicit_player_and_character_targets():
    now = datetime.now(UTC)
    policy = RelationshipPolicy(
        RelationshipValues(50, 50, 0),
        60,
        60,
        frozenset({RelationshipEvidenceKind.INTERACTION}),
        frozenset({RelationshipEvidenceKind.SUPPORT}),
        frozenset({RelationshipEvidenceKind.COMMITMENT}),
    )
    for kind in ("player", "character"):
        key = RelationshipKey("community", "observer", kind, "target")
        evidence = RelationshipEvidence(uuid4(), key, "interaction", "message", "source", now, now)
        state = RelationshipState.stranger(key, updated_at_utc=now)
        impact = RelationshipImpact(
            evidence.evidence_id, RelationshipDimension.AFFECTION, RelationshipDirection.UP, 3
        )
        transition = apply_relationship_evidence(
            state, evidence, (impact,), policy, expected_version=0, updated_at_utc=now
        )
        assert transition.state.values.affection == 53
        assert transition.state.state_version == 1
        assert transition.state.key.target_kind.value == kind
        with pytest.raises(DomainInvariantError):
            apply_relationship_evidence(
                transition.state,
                evidence,
                (impact,),
                policy,
                expected_version=0,
                updated_at_utc=now,
            )
