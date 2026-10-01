from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

from echo_commons.agents.contracts import CharacterStateSnapshot, RelationshipStateSnapshot
from echo_commons.agents.harness.prompt import render_character_state, render_relationship_state
from echo_commons.domain.character_state_entry import CharacterStateEntry, CharacterStateKind
from echo_commons.domain.relationship import (
    RelationshipEvidence,
    RelationshipEvidenceKind,
    RelationshipKey,
    RelationshipState,
    RelationshipTargetKind,
    RelationshipType,
    RelationshipValues,
)
from echo_commons.store.database import Database
from echo_commons.store.migrations import migrate
from echo_commons.store.state_repositories import (
    CharacterStateEntryRepository,
    RelationshipEvidenceRepository,
    RelationshipStateRepository,
)

BASE_TIME = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def database(tmp_path):
    database = Database(str(tmp_path / "state.sqlite3"))
    await migrate(database)
    yield database
    await database.close()


def make_state_entry(
    *,
    character_id: str,
    state_kind: CharacterStateKind,
    state_version: int,
    value: str,
    source_ref: str,
    recorded_at_utc: datetime,
    expires_at_utc: datetime | None = None,
) -> CharacterStateEntry:
    return CharacterStateEntry(
        entry_id=uuid4(),
        character_id=character_id,
        state_kind=state_kind,
        value=value,
        source_kind="test",
        source_ref=source_ref,
        state_version=state_version,
        recorded_at_utc=recorded_at_utc,
        expires_at_utc=expires_at_utc,
    )


def make_relationship_key(
    account_id: str = "account-1", observer_character_id: str = "xiaojin"
) -> RelationshipKey:
    return RelationshipKey(
        account_id=account_id,
        observer_character_id=observer_character_id,
        target_kind=RelationshipTargetKind.ACCOUNT,
        target_id=account_id,
    )


@pytest.mark.asyncio
async def test_character_state_repository_appends_by_category_and_keeps_expired_latest(
    database,
):
    repository = CharacterStateEntryRepository(database)
    previous = make_state_entry(
        character_id="xiaojin",
        state_kind=CharacterStateKind.PHYSICAL,
        state_version=1,
        value="之前身体状态不错",
        source_ref="physical-1",
        recorded_at_utc=BASE_TIME - timedelta(hours=1),
    )
    expired = make_state_entry(
        character_id="xiaojin",
        state_kind=CharacterStateKind.PHYSICAL,
        state_version=2,
        value="短暂有些疲惫",
        source_ref="physical-2",
        recorded_at_utc=BASE_TIME - timedelta(minutes=2),
        expires_at_utc=BASE_TIME - timedelta(minutes=1),
    )
    mood = make_state_entry(
        character_id="xiaojin",
        state_kind=CharacterStateKind.MOOD,
        state_version=1,
        value="心情平静",
        source_ref="mood-1",
        recorded_at_utc=BASE_TIME - timedelta(minutes=1),
    )

    async with database.transaction(immediate=True) as connection:
        await repository.append(previous, expected_version=0, connection=connection)
    async with database.transaction(immediate=True) as connection:
        await repository.append(expired, expected_version=1, connection=connection)
        await repository.append(mood, expected_version=0, connection=connection)

    latest = await repository.list_latest_for_character("xiaojin")
    latest_by_kind = {entry.state_kind: entry for entry in latest}
    assert latest_by_kind == {
        CharacterStateKind.PHYSICAL: expired,
        CharacterStateKind.MOOD: mood,
    }
    assert not latest_by_kind[CharacterStateKind.PHYSICAL].is_unexpired_at(BASE_TIME)
    assert latest_by_kind[CharacterStateKind.MOOD].is_unexpired_at(BASE_TIME)

    stale = make_state_entry(
        character_id="xiaojin",
        state_kind=CharacterStateKind.PHYSICAL,
        state_version=2,
        value="过期写入",
        source_ref="physical-stale",
        recorded_at_utc=BASE_TIME,
    )
    with pytest.raises(RuntimeError, match="character state entry"):
        async with database.transaction(immediate=True) as connection:
            await repository.append(stale, expected_version=1, connection=connection)

    duplicate_source = make_state_entry(
        character_id="xiaojin",
        state_kind=CharacterStateKind.PHYSICAL,
        state_version=3,
        value="重复来源",
        source_ref="physical-2",
        recorded_at_utc=BASE_TIME,
    )
    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await repository.append(duplicate_source, expected_version=2, connection=connection)

    assert {
        entry.state_kind: entry for entry in await repository.list_latest_for_character("xiaojin")
    }[CharacterStateKind.PHYSICAL] == expired
    with pytest.raises(RuntimeError, match="explicit transaction"):
        await repository.append(
            make_state_entry(
                character_id="xiaojin",
                state_kind=CharacterStateKind.ACTIVITY,
                state_version=1,
                value="正在散步",
                source_ref="activity-1",
                recorded_at_utc=BASE_TIME,
            ),
            expected_version=0,
        )


@pytest.mark.asyncio
async def test_relationship_repositories_round_trip_scoped_state_and_evidence(database):
    evidence_repository = RelationshipEvidenceRepository(database)
    state_repository = RelationshipStateRepository(database)
    key = make_relationship_key()
    evidence = RelationshipEvidence(
        evidence_id=uuid4(),
        key=key,
        evidence_kind=RelationshipEvidenceKind.INTERACTION,
        source_kind="message",
        source_ref="message-1",
        occurred_at_utc=BASE_TIME,
        recorded_at_utc=BASE_TIME,
    )
    first_state = RelationshipState(
        key=key,
        relationship_type=RelationshipType.ACQUAINTANCE,
        values=RelationshipValues(affection=24, trust=18, attachment=3),
        state_version=1,
        updated_at_utc=BASE_TIME,
        attitude_summary="愿意认真听对方说完",
        attitude_source_refs=(evidence.evidence_id,),
    )

    async with database.transaction(immediate=True) as connection:
        await evidence_repository.append(evidence, connection=connection)
        await state_repository.save(first_state, expected_version=0, connection=connection)

    assert await evidence_repository.get(evidence.evidence_id) == evidence
    assert await state_repository.get(key) == first_state
    assert await state_repository.get(make_relationship_key("account-2")) is None

    next_state = RelationshipState(
        key=key,
        relationship_type=RelationshipType.ACQUAINTANCE,
        values=RelationshipValues(affection=27, trust=18, attachment=3),
        state_version=2,
        updated_at_utc=BASE_TIME + timedelta(minutes=1),
        attitude_summary=first_state.attitude_summary,
        attitude_source_refs=first_state.attitude_source_refs,
    )
    async with database.transaction(immediate=True) as connection:
        await state_repository.save(next_state, expected_version=1, connection=connection)

    stale_state = RelationshipState(
        key=key,
        relationship_type=RelationshipType.ACQUAINTANCE,
        values=RelationshipValues(affection=28, trust=18, attachment=3),
        state_version=2,
        updated_at_utc=BASE_TIME + timedelta(minutes=2),
        attitude_summary=first_state.attitude_summary,
        attitude_source_refs=first_state.attitude_source_refs,
    )
    with pytest.raises(RuntimeError, match="relationship state"):
        async with database.transaction(immediate=True) as connection:
            await state_repository.save(stale_state, expected_version=1, connection=connection)
    assert await state_repository.get(key) == next_state

    repeated_source = RelationshipEvidence(
        evidence_id=uuid4(),
        key=key,
        evidence_kind=RelationshipEvidenceKind.INTERACTION,
        source_kind="message",
        source_ref="message-1",
        occurred_at_utc=BASE_TIME,
        recorded_at_utc=BASE_TIME,
    )
    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await evidence_repository.append(repeated_source, connection=connection)

    wrong_scope_key = make_relationship_key("account-3")
    friend_state = RelationshipState(
        key=wrong_scope_key,
        relationship_type=RelationshipType.FRIEND,
        values=RelationshipValues(affection=60, trust=60, attachment=20),
        state_version=1,
        updated_at_utc=BASE_TIME,
        friend_qualifying_evidence_id=evidence.evidence_id,
    )
    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await state_repository.save(friend_state, expected_version=0, connection=connection)
    assert await state_repository.get(wrong_scope_key) is None


def test_prompt_projection_uses_named_state_and_relationship_without_raw_scores():
    character_state = CharacterStateSnapshot(
        character_id="xiaojin",
        physical_condition="肩膀有些酸",
        mood="有点烦",
        current_activity="修改一幅画",
    )
    relationship_state = RelationshipStateSnapshot(
        subject_id="account-1",
        relationship_type="friend",
        affection=87,
        trust=76,
        attachment=54,
        attitude_summary="愿意主动关心对方最近过得如何。",
    )

    character_text = render_character_state(character_state)
    relationship_text = render_relationship_state(relationship_state)

    assert "肩膀有些酸" in character_text
    assert "心情是有点烦" in character_text
    assert "修改一幅画" in character_text
    assert "你和对方已经是朋友。" in relationship_text
    assert relationship_state.attitude_summary in relationship_text
    for score in ("87", "76", "54", "account-1", "state_version"):
        assert score not in character_text + relationship_text
