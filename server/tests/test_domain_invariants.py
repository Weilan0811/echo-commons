from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from echo_server.domain.conversation import (
    Conversation,
    ConversationKind,
    ConversationParticipant,
)
from echo_server.domain.errors import DomainInvariantError
from echo_server.domain.input_batch import InputBatch, InputBatchStatus
from echo_server.domain.messages import Message
from echo_server.domain.result import AgentResult, AgentResultStatus, project_bubbles
from echo_server.domain.state import (
    CharacterAvailabilityStatus,
    CharacterState,
    EligibilityRequest,
    WorldState,
    WorldStatus,
    evaluate_response_eligibility,
)
from echo_server.domain.task import ConversationTask, TaskStatus

BASE_TIME = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def build_task(*, now_utc: datetime = BASE_TIME) -> ConversationTask:
    return ConversationTask.create(
        task_id=uuid4(),
        account_id="account",
        conversation_id="conversation",
        character_id="xiaojin",
        input_max_message_sequence=2,
        context_max_message_sequence=3,
        world_state_version=4,
        character_state_version=5,
        context_version="context-1",
        trace_id=uuid4(),
        now_utc=now_utc,
    )


def build_result(*, now_utc: datetime = BASE_TIME) -> AgentResult:
    return AgentResult(
        result_id=uuid4(),
        task_id=uuid4(),
        attempt_no=1,
        agent_id="character-agent",
        agent_kind="character",
        invocation_id=uuid4(),
        result_kind="character_message",
        schema_version="v1",
        context_version="context-1",
        payload_json='{"utterance":"hello"}',
        created_at_utc=now_utc,
    )


def test_message_factories_enforce_runtime_relationships_and_keep_legacy_shape_readable():
    batch_id = uuid4()
    result_id = uuid4()
    player = Message.player(
        message_sequence=1,
        message_id=uuid4(),
        account_id="account",
        conversation_id="conversation",
        sender_id="player",
        text="hello",
        images=(),
        client_msg_id=uuid4(),
        client_timestamp_utc=BASE_TIME,
        server_timestamp_utc=BASE_TIME,
        input_batch_id=batch_id,
        reply_to_message_id=None,
        trace_id=uuid4(),
    )
    character = Message.character(
        message_sequence=2,
        message_id=uuid4(),
        account_id="account",
        conversation_id="conversation",
        character_id="xiaojin",
        text="hi",
        server_timestamp_utc=BASE_TIME,
        result_id=result_id,
        bubble_index=0,
        reply_to_message_id=player.message_id,
        trace_id=uuid4(),
    )

    assert player.input_batch_id == batch_id
    assert character.result_id == result_id
    assert character.bubble_index == 0
    with pytest.raises(DomainInvariantError):
        replace(player, result_id=result_id)
    with pytest.raises(DomainInvariantError):
        replace(character, bubble_index=-1)
    with pytest.raises(FrozenInstanceError):
        player.text = "changed"


def test_input_batch_resets_quiet_window_and_has_one_way_assignment():
    batch = InputBatch.start(
        input_batch_id=uuid4(),
        account_id="account",
        conversation_id="conversation",
        now_utc=BASE_TIME,
    )
    first = batch.append_message(message_sequence=10, now_utc=BASE_TIME)
    second = first.append_message(
        message_sequence=11,
        now_utc=BASE_TIME + timedelta(seconds=3),
    )

    assert second.quiet_until_utc == BASE_TIME + timedelta(seconds=9)
    with pytest.raises(DomainInvariantError):
        second.seal(now_utc=BASE_TIME + timedelta(seconds=8))

    waiting = second.seal(now_utc=BASE_TIME + timedelta(seconds=9))
    assigned = waiting.assign(task_id=uuid4(), now_utc=BASE_TIME + timedelta(seconds=10))
    covered = assigned.cover(now_utc=BASE_TIME + timedelta(seconds=11))
    assert waiting.status is InputBatchStatus.WAITING
    assert covered.status is InputBatchStatus.COVERED
    with pytest.raises(DomainInvariantError):
        assigned.append_message(message_sequence=12, now_utc=BASE_TIME + timedelta(seconds=12))


def test_input_batch_rejects_non_monotonic_message_sequences():
    batch = InputBatch.start(
        input_batch_id=uuid4(),
        account_id="account",
        conversation_id="conversation",
        now_utc=BASE_TIME,
    ).append_message(message_sequence=2, now_utc=BASE_TIME)
    with pytest.raises(DomainInvariantError):
        batch.append_message(message_sequence=2, now_utc=BASE_TIME + timedelta(seconds=1))


def test_task_claim_retry_failure_and_deferred_resume_preserve_attempt_semantics():
    task = build_task()
    claimed = task.claim(
        worker_id="worker-1",
        now_utc=BASE_TIME,
        lease_until_utc=BASE_TIME + timedelta(seconds=30),
    )
    retry_wait = claimed.retry_or_fail(
        worker_id="worker-1",
        now_utc=BASE_TIME + timedelta(seconds=1),
        available_at_utc=BASE_TIME + timedelta(seconds=2),
        error_code="provider_timeout",
        max_attempts=2,
    )
    assert retry_wait.status is TaskStatus.RETRY_WAIT
    assert retry_wait.attempt_count == 1
    assert claimed.lease_generation == 1

    reclaimed = retry_wait.claim(
        worker_id="worker-2",
        now_utc=BASE_TIME + timedelta(seconds=2),
        lease_until_utc=BASE_TIME + timedelta(seconds=32),
    )
    failed = reclaimed.retry_or_fail(
        worker_id="worker-2",
        now_utc=BASE_TIME + timedelta(seconds=3),
        available_at_utc=BASE_TIME + timedelta(seconds=3),
        error_code="provider_timeout",
        max_attempts=2,
    )
    assert failed.status is TaskStatus.FAILED
    assert failed.attempt_count == 2
    assert reclaimed.lease_generation == 2
    with pytest.raises(DomainInvariantError):
        failed.claim(
            worker_id="worker-3",
            now_utc=BASE_TIME + timedelta(seconds=4),
            lease_until_utc=BASE_TIME + timedelta(seconds=34),
        )

    deferred = claimed.defer(
        worker_id="worker-1",
        now_utc=BASE_TIME + timedelta(seconds=2),
        reason_code="character_offline",
        available_at_utc=BASE_TIME + timedelta(seconds=20),
    )
    resumed = deferred.resume(now_utc=BASE_TIME + timedelta(seconds=20))
    assert resumed.status is TaskStatus.PENDING
    assert resumed.attempt_count == claimed.attempt_count


def test_expired_task_lease_becomes_retryable():
    claimed = build_task().claim(
        worker_id="worker-1",
        now_utc=BASE_TIME,
        lease_until_utc=BASE_TIME + timedelta(seconds=5),
    )
    recovered = claimed.recover_expired(now_utc=BASE_TIME + timedelta(seconds=5))
    assert recovered.status is TaskStatus.RETRY_WAIT
    assert recovered.lease_owner is None
    assert recovered.last_error_code == "lease_expired"
    assert recovered.lease_generation == claimed.lease_generation


def test_task_lease_renewal_requires_the_current_fencing_identity():
    claimed = build_task().claim(
        worker_id="worker-1",
        now_utc=BASE_TIME,
        lease_until_utc=BASE_TIME + timedelta(seconds=5),
    )
    renewed = claimed.renew_lease(
        worker_id="worker-1",
        now_utc=BASE_TIME + timedelta(seconds=2),
        lease_until_utc=BASE_TIME + timedelta(seconds=7),
        attempt_count=claimed.attempt_count,
        lease_generation=claimed.lease_generation,
    )
    assert renewed.lease_until_utc == BASE_TIME + timedelta(seconds=7)

    with pytest.raises(DomainInvariantError):
        claimed.renew_lease(
            worker_id="worker-1",
            now_utc=BASE_TIME + timedelta(seconds=2),
            lease_until_utc=BASE_TIME + timedelta(seconds=7),
            attempt_count=claimed.attempt_count,
            lease_generation=claimed.lease_generation + 1,
        )

    with pytest.raises(DomainInvariantError, match="time cannot move backwards"):
        claimed.renew_lease(
            worker_id="worker-1",
            now_utc=BASE_TIME - timedelta(seconds=1),
            lease_until_utc=BASE_TIME + timedelta(seconds=7),
            attempt_count=claimed.attempt_count,
            lease_generation=claimed.lease_generation,
        )


def test_eligibility_records_all_blocking_reasons_and_state_versions():
    world = WorldState(
        state_version=7,
        world_time_utc=BASE_TIME,
        updated_at_utc=BASE_TIME,
        status=WorldStatus.PAUSED,
    )
    character = CharacterState(
        character_id="xiaojin",
        availability_status=CharacterAvailabilityStatus.OFFLINE,
        state_version=8,
        updated_at_utc=BASE_TIME,
        next_check_at_utc=BASE_TIME + timedelta(minutes=5),
    )
    decision = evaluate_response_eligibility(EligibilityRequest(world, character))

    assert not decision.allowed
    assert decision.reason_codes == ("world_unavailable", "character_offline")
    assert decision.world_state_version == 7
    assert decision.character_state_version == 8
    assert decision.next_check_at_utc == BASE_TIME + timedelta(minutes=5)


def test_conversation_capability_and_participant_lifecycle_are_explicit():
    direct = Conversation(
        conversation_id="direct",
        account_id="account",
        kind=ConversationKind.DIRECT,
        created_at_utc=BASE_TIME,
        updated_at_utc=BASE_TIME,
    )
    group = Conversation(
        conversation_id="group",
        account_id="account",
        kind=ConversationKind.GROUP,
        created_at_utc=BASE_TIME,
        updated_at_utc=BASE_TIME,
    )
    participant = ConversationParticipant(
        conversation_id="direct",
        character_id="xiaojin",
        joined_at_utc=BASE_TIME,
    )

    assert direct.can_execute_agent
    assert not group.can_execute_agent
    assert participant.is_active
    assert not participant.leave(now_utc=BASE_TIME + timedelta(seconds=1)).is_active


def test_approved_result_projects_contiguous_future_bubbles():
    result = build_result().approve(decided_at_utc=BASE_TIME + timedelta(seconds=1))
    bubbles = project_bubbles(result, ("first", "second"))

    assert result.status is AgentResultStatus.APPROVED
    assert [(bubble.result_id, bubble.bubble_index, bubble.text) for bubble in bubbles] == [
        (result.result_id, 0, "first"),
        (result.result_id, 1, "second"),
    ]
    with pytest.raises(DomainInvariantError):
        result.approve(decided_at_utc=BASE_TIME + timedelta(seconds=2))
    with pytest.raises(DomainInvariantError):
        project_bubbles(build_result(), ("not approved",))
