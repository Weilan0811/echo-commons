from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from echo_server.domain.character_state_entry import (
    CharacterStateKind,
    replace_character_state_entry,
)
from echo_server.domain.errors import DomainInvariantError
from echo_server.domain.relationship import (
    RelationshipAttitude,
    RelationshipDimension,
    RelationshipEvidence,
    RelationshipEvidenceKind,
    RelationshipImpact,
    RelationshipKey,
    RelationshipPolicy,
    RelationshipState,
    RelationshipStepMultiplier,
    RelationshipTargetKind,
    RelationshipType,
    RelationshipValues,
    apply_relationship_evidence,
)

BASE_TIME = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def build_key() -> RelationshipKey:
    return RelationshipKey(
        account_id="player-1",
        observer_character_id="xiaojin",
        target_kind=RelationshipTargetKind.ACCOUNT,
        target_id="player-1",
    )


def build_evidence(
    *,
    evidence_kind: RelationshipEvidenceKind | str,
    evidence_id=None,
    key: RelationshipKey | None = None,
    source_ref: str = "message-1",
    occurred_at_utc: datetime = BASE_TIME,
) -> RelationshipEvidence:
    return RelationshipEvidence(
        evidence_id=uuid4() if evidence_id is None else evidence_id,
        key=build_key() if key is None else key,
        evidence_kind=evidence_kind,
        source_kind="message",
        source_ref=source_ref,
        occurred_at_utc=occurred_at_utc,
        recorded_at_utc=occurred_at_utc + timedelta(seconds=1),
    )


def build_policy(
    *,
    baseline: RelationshipValues | None = None,
    minimum_affection: float = 70,
    minimum_trust: float = 70,
    initializes_on: frozenset[RelationshipEvidenceKind] = frozenset(
        {RelationshipEvidenceKind.INTERACTION}
    ),
    friend_kinds: frozenset[RelationshipEvidenceKind] = frozenset(
        {RelationshipEvidenceKind.SUPPORT}
    ),
    attachment_kinds: frozenset[RelationshipEvidenceKind] = frozenset(
        {RelationshipEvidenceKind.SUPPORT}
    ),
    multipliers: tuple[RelationshipStepMultiplier, ...] = (),
) -> RelationshipPolicy:
    return RelationshipPolicy(
        acquaintance_baseline=(
            RelationshipValues(affection=40, trust=30, attachment=5)
            if baseline is None
            else baseline
        ),
        friend_minimum_affection=minimum_affection,
        friend_minimum_trust=minimum_trust,
        initializes_on=initializes_on,
        friend_qualifying_kinds=friend_kinds,
        attachment_qualifying_kinds=attachment_kinds,
        step_multipliers=multipliers,
    )


def test_new_relationship_is_a_stranger_without_relationship_scores():
    state = RelationshipState.stranger(build_key(), updated_at_utc=BASE_TIME)

    assert state.relationship_type is RelationshipType.STRANGER
    assert not state.initialized
    assert state.values is None
    assert state.state_version == 0

    with pytest.raises(DomainInvariantError):
        replace(state, values=RelationshipValues(affection=0, trust=0, attachment=0))
    with pytest.raises(DomainInvariantError):
        replace(state, relationship_type=RelationshipType.ACQUAINTANCE)


def test_only_a_configured_real_interaction_initializes_the_relationship():
    state = RelationshipState.stranger(build_key(), updated_at_utc=BASE_TIME)
    policy = build_policy()
    incidental = build_evidence(evidence_kind=RelationshipEvidenceKind.CONFLICT)

    unchanged = apply_relationship_evidence(
        state,
        incidental,
        (),
        policy,
        expected_version=0,
        updated_at_utc=incidental.recorded_at_utc,
    )
    assert unchanged.state is state
    assert not unchanged.changed

    first_interaction = build_evidence(
        evidence_kind=RelationshipEvidenceKind.INTERACTION,
        source_ref="message-2",
        occurred_at_utc=BASE_TIME + timedelta(minutes=1),
    )
    initialized = apply_relationship_evidence(
        state,
        first_interaction,
        (),
        policy,
        expected_version=0,
        updated_at_utc=first_interaction.recorded_at_utc,
    )

    assert initialized.state.relationship_type is RelationshipType.ACQUAINTANCE
    assert initialized.state.initialized
    assert initialized.state.values == RelationshipValues(affection=40, trust=30, attachment=5)
    assert initialized.state.state_version == 1
    assert initialized.initialized_now


def test_evidence_applies_discrete_steps_with_directional_attenuation():
    state = RelationshipState(
        key=build_key(),
        relationship_type=RelationshipType.ACQUAINTANCE,
        values=RelationshipValues(affection=40, trust=20, attachment=10),
        state_version=3,
        updated_at_utc=BASE_TIME,
    )
    evidence = build_evidence(evidence_kind=RelationshipEvidenceKind.SUPPORT)
    impacts = (
        RelationshipImpact(evidence.evidence_id, "affection", "up", 1),
        RelationshipImpact(evidence.evidence_id, "trust", "down", 2),
        RelationshipImpact(evidence.evidence_id, "attachment", "up", 1),
    )

    result = apply_relationship_evidence(
        state,
        evidence,
        impacts,
        build_policy(),
        expected_version=3,
        updated_at_utc=evidence.recorded_at_utc,
    )

    assert result.state.values is not None
    assert result.state.values.affection == pytest.approx(40.6)
    assert result.state.values.trust == pytest.approx(19.4)
    assert result.state.values.attachment == pytest.approx(10.9)
    assert [item.delta for item in result.applied_impacts] == pytest.approx([0.6, -0.6, 0.9])
    assert result.state.state_version == 4
    assert result.changed


def test_ordinary_evidence_does_not_raise_attachment_and_scores_are_clamped():
    state = RelationshipState(
        key=build_key(),
        relationship_type=RelationshipType.ACQUAINTANCE,
        values=RelationshipValues(affection=99.5, trust=0.5, attachment=20),
        state_version=1,
        updated_at_utc=BASE_TIME,
    )
    evidence = build_evidence(evidence_kind=RelationshipEvidenceKind.INTERACTION)
    impacts = (
        RelationshipImpact(evidence.evidence_id, "affection", "up", 3),
        RelationshipImpact(evidence.evidence_id, "trust", "down", 3),
        RelationshipImpact(evidence.evidence_id, "attachment", "up", 3),
    )

    result = apply_relationship_evidence(
        state,
        evidence,
        impacts,
        build_policy(),
        expected_version=1,
        updated_at_utc=evidence.recorded_at_utc,
    )

    assert result.state.values == RelationshipValues(affection=99.53, trust=0.47, attachment=20)
    assert result.applied_impacts[2].delta == 0


def test_relationship_type_multiplier_is_applied_to_the_configured_axis():
    state = RelationshipState(
        key=build_key(),
        relationship_type=RelationshipType.ACQUAINTANCE,
        values=RelationshipValues(affection=50, trust=50, attachment=0),
        state_version=1,
        updated_at_utc=BASE_TIME,
    )
    evidence = build_evidence(evidence_kind=RelationshipEvidenceKind.INTERACTION)
    impact = RelationshipImpact(evidence.evidence_id, "affection", "up", 1)
    policy = build_policy(
        multipliers=(
            RelationshipStepMultiplier(
                relationship_type=RelationshipType.ACQUAINTANCE,
                dimension=RelationshipDimension.AFFECTION,
                multiplier=2,
            ),
        )
    )

    result = apply_relationship_evidence(
        state,
        evidence,
        (impact,),
        policy,
        expected_version=1,
        updated_at_utc=evidence.recorded_at_utc,
    )

    assert result.state.values is not None
    assert result.state.values.affection == pytest.approx(51)


def test_friend_requires_a_qualifying_event_and_both_configured_thresholds():
    state = RelationshipState.stranger(build_key(), updated_at_utc=BASE_TIME)
    policy = build_policy(
        baseline=RelationshipValues(affection=50, trust=50, attachment=0),
        minimum_affection=50,
        minimum_trust=50,
    )
    initialized_event = build_evidence(evidence_kind=RelationshipEvidenceKind.INTERACTION)
    acquaintance = apply_relationship_evidence(
        state,
        initialized_event,
        (),
        policy,
        expected_version=0,
        updated_at_utc=initialized_event.recorded_at_utc,
    ).state
    assert acquaintance.relationship_type is RelationshipType.ACQUAINTANCE

    qualifying_event = build_evidence(
        evidence_kind=RelationshipEvidenceKind.SUPPORT,
        source_ref="message-2",
        occurred_at_utc=BASE_TIME + timedelta(minutes=1),
    )
    promoted = apply_relationship_evidence(
        acquaintance,
        qualifying_event,
        (),
        policy,
        expected_version=acquaintance.state_version,
        updated_at_utc=qualifying_event.recorded_at_utc,
    )
    assert promoted.state.relationship_type is RelationshipType.FRIEND
    assert promoted.state.friend_qualifying_evidence_id == qualifying_event.evidence_id
    assert promoted.promoted_to_friend


def test_friend_qualification_is_remembered_until_both_thresholds_are_met():
    state = RelationshipState(
        key=build_key(),
        relationship_type=RelationshipType.ACQUAINTANCE,
        values=RelationshipValues(affection=49, trust=49, attachment=0),
        state_version=2,
        updated_at_utc=BASE_TIME,
    )
    policy = build_policy(minimum_affection=50, minimum_trust=50)
    support = build_evidence(evidence_kind=RelationshipEvidenceKind.SUPPORT)
    first = apply_relationship_evidence(
        state,
        support,
        (
            RelationshipImpact(support.evidence_id, "affection", "up", 1),
            RelationshipImpact(support.evidence_id, "trust", "up", 1),
        ),
        policy,
        expected_version=2,
        updated_at_utc=support.recorded_at_utc,
    )
    assert first.state.relationship_type is RelationshipType.ACQUAINTANCE
    assert first.state.friend_qualifying_evidence_id == support.evidence_id

    later = build_evidence(
        evidence_kind=RelationshipEvidenceKind.INTERACTION,
        source_ref="message-2",
        occurred_at_utc=BASE_TIME + timedelta(minutes=1),
    )
    second = apply_relationship_evidence(
        first.state,
        later,
        (
            RelationshipImpact(later.evidence_id, "affection", "up", 1),
            RelationshipImpact(later.evidence_id, "trust", "up", 1),
        ),
        policy,
        expected_version=first.state.state_version,
        updated_at_utc=later.recorded_at_utc,
    )
    assert second.state.values is not None
    assert second.state.values.affection >= 50
    assert second.state.values.trust >= 50
    assert second.state.relationship_type is RelationshipType.FRIEND


def test_attitude_summary_requires_a_source_and_version_conflicts_are_rejected():
    state = RelationshipState(
        key=build_key(),
        relationship_type=RelationshipType.ACQUAINTANCE,
        values=RelationshipValues(affection=50, trust=50, attachment=0),
        state_version=4,
        updated_at_utc=BASE_TIME,
    )
    evidence = build_evidence(evidence_kind=RelationshipEvidenceKind.INTERACTION)

    with pytest.raises(DomainInvariantError, match="version conflict"):
        apply_relationship_evidence(
            state,
            evidence,
            (),
            build_policy(),
            expected_version=3,
            updated_at_utc=evidence.recorded_at_utc,
        )

    with pytest.raises(DomainInvariantError, match="supporting evidence"):
        RelationshipAttitude(summary="相处起来还不太熟。", evidence_refs=())

    attitude = RelationshipAttitude(
        summary="相处起来还不太熟。",
        evidence_refs=(evidence.evidence_id,),
    )
    result = apply_relationship_evidence(
        state,
        evidence,
        (),
        build_policy(),
        expected_version=4,
        updated_at_utc=evidence.recorded_at_utc,
        attitude=attitude,
    )
    assert result.state.attitude_summary == attitude.summary
    assert result.state.attitude_source_refs == attitude.evidence_refs
    assert result.state.state_version == 5
    assert result.changed


def test_evidence_scope_and_one_impact_per_axis_are_enforced():
    state = RelationshipState.stranger(build_key(), updated_at_utc=BASE_TIME)
    wrong_key = RelationshipKey(
        account_id="player-2",
        observer_character_id="xiaojin",
        target_kind="account",
        target_id="player-2",
    )
    evidence = build_evidence(evidence_kind=RelationshipEvidenceKind.INTERACTION, key=wrong_key)
    with pytest.raises(DomainInvariantError, match="different directed relation"):
        apply_relationship_evidence(
            state,
            evidence,
            (),
            build_policy(),
            expected_version=0,
            updated_at_utc=evidence.recorded_at_utc,
        )

    valid = build_evidence(evidence_kind=RelationshipEvidenceKind.INTERACTION)
    initialized = apply_relationship_evidence(
        state,
        valid,
        (),
        build_policy(),
        expected_version=0,
        updated_at_utc=valid.recorded_at_utc,
    )
    assert initialized.state.relationship_type is RelationshipType.ACQUAINTANCE
    replay = build_evidence(
        evidence_kind=RelationshipEvidenceKind.INTERACTION,
        source_ref="message-2",
        occurred_at_utc=BASE_TIME + timedelta(minutes=1),
    )
    with pytest.raises(DomainInvariantError, match="at most once"):
        apply_relationship_evidence(
            initialized.state,
            replay,
            (
                RelationshipImpact(replay.evidence_id, "affection", "up", 1),
                RelationshipImpact(replay.evidence_id, "affection", "down", 1),
            ),
            build_policy(),
            expected_version=initialized.state.state_version,
            updated_at_utc=replay.recorded_at_utc,
        )


def test_character_state_entry_ttl_crosses_midnight_and_expires_deterministically():
    entry_id = uuid4()
    activity = replace_character_state_entry(
        None,
        entry_id=entry_id,
        character_id="xiaojin",
        state_kind=CharacterStateKind.ACTIVITY,
        value="整理画具",
        source_kind="reflection",
        source_ref="phase-1",
        expected_version=0,
        recorded_at_utc=BASE_TIME,
        expires_at_utc=BASE_TIME + timedelta(hours=14),
    )
    assert activity.is_unexpired_at(BASE_TIME + timedelta(hours=12))
    assert not activity.is_unexpired_at(BASE_TIME + timedelta(hours=14))

    next_day = replace_character_state_entry(
        activity,
        entry_id=uuid4(),
        character_id="xiaojin",
        state_kind="activity",
        value="准备睡觉",
        source_kind="reflection",
        source_ref="phase-2",
        expected_version=1,
        recorded_at_utc=BASE_TIME + timedelta(days=1),
    )
    assert next_day.state_version == 2


def test_replacing_a_character_state_appends_a_version_and_checks_compare_version():
    first = replace_character_state_entry(
        None,
        entry_id=uuid4(),
        character_id="xiaojin",
        state_kind="mood",
        value="有些挂心",
        source_kind="reflection",
        source_ref="phase-1",
        expected_version=0,
        recorded_at_utc=BASE_TIME,
        expires_at_utc=BASE_TIME + timedelta(days=3),
    )
    second_time = BASE_TIME + timedelta(days=1)
    second = replace_character_state_entry(
        first,
        entry_id=uuid4(),
        character_id="xiaojin",
        state_kind="mood",
        value="稍微轻松了些",
        source_kind="reflection",
        source_ref="phase-2",
        expected_version=1,
        recorded_at_utc=second_time,
    )

    assert first.value == "有些挂心"
    assert second.state_version == 2

    with pytest.raises(DomainInvariantError, match="version conflict"):
        replace_character_state_entry(
            second,
            entry_id=uuid4(),
            character_id="xiaojin",
            state_kind="mood",
            value="又变了",
            source_kind="reflection",
            source_ref="phase-3",
            expected_version=1,
            recorded_at_utc=BASE_TIME + timedelta(days=2),
        )


def test_character_state_entry_rejects_invalid_ttl_or_mixed_state_slot():
    first = replace_character_state_entry(
        None,
        entry_id=uuid4(),
        character_id="xiaojin",
        state_kind="physical",
        value="有点累",
        source_kind="reflection",
        source_ref="phase-1",
        expected_version=0,
        recorded_at_utc=BASE_TIME,
        expires_at_utc=BASE_TIME + timedelta(hours=1),
    )

    with pytest.raises(DomainInvariantError, match="later than recorded_at"):
        replace_character_state_entry(
            None,
            entry_id=uuid4(),
            character_id="xiaojin",
            state_kind="activity",
            value="整理画具",
            source_kind="reflection",
            source_ref="phase-2",
            expected_version=0,
            recorded_at_utc=BASE_TIME,
            expires_at_utc=BASE_TIME,
        )
    with pytest.raises(DomainInvariantError, match="different state slot"):
        replace_character_state_entry(
            first,
            entry_id=uuid4(),
            character_id="xiaojin",
            state_kind="mood",
            value="心情尚可",
            source_kind="reflection",
            source_ref="phase-2",
            expected_version=1,
            recorded_at_utc=BASE_TIME + timedelta(minutes=1),
        )
