from concurrent.futures import ThreadPoolExecutor

import pytest
from historical_messages import historical_message
from test_message_perspective import build_system, send

from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.sources import SourceKind
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.sealing import MemorySealing
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


def sealing(system):
    return MemorySealing(
        system.database,
        InstanceRepository(),
        ConversationRepository(),
        system.world,
        SegmentRepository(),
        ThoughtRepository(),
    )


def message_ids(segment):
    return tuple(
        source.source_id for source in segment.sources if source.kind is SourceKind.MESSAGE
    )


def test_segments_keep_exact_visible_sources_and_sender_identity(tmp_path):
    system = build_system(tmp_path)
    first = send(system, "大家好")
    private = historical_message(
        system, "只有小槿一号能看到", recipients=(ActorRef("character", "first"),)
    )
    last = send(system, "今天一起玩", player="bob")
    service = sealing(system)
    first_segment = service.seal("community", "first")
    second_segment = service.seal("community", "second")
    assert first_segment.segment_id != second_segment.segment_id
    assert message_ids(first_segment) == (first.message_id, private.message_id, last.message_id)
    assert message_ids(second_segment) == (first.message_id, last.message_id)
    assert second_segment.position == 1
    assert second_segment.started_at_utc == first.created_at_utc
    assert second_segment.ended_at_utc == last.created_at_utc
    with system.database.read() as connection:
        senders = tuple(
            system.messages.get(connection, "conversation", source).sender
            for source in message_ids(second_segment)
        )
    assert senders == (ActorRef("player", "alice"), ActorRef("player", "bob"))
    assert service.seal("community", "first") is None
    assert service.seal("community", "second") is None
    following = send(system, "继续聊天")
    assert message_ids(service.seal("community", "second")) == (following.message_id,)


def test_rejoining_segments_preserve_historical_visibility(tmp_path):
    system = build_system(tmp_path)
    before = send(system, "离开前的消息")
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    hidden = send(system, "离开期间的消息")
    system.conversations.join("community", "conversation", ActorRef("character", "first"))
    after = send(system, "回来后的消息")
    service = sealing(system)
    left = service.seal("community", "first")
    right = service.seal("community", "first")
    assert message_ids(left) == (before.message_id,)
    assert message_ids(right) == (after.message_id,)
    assert hidden.message_id not in (*message_ids(left), *message_ids(right))


def test_parallel_sealing_claims_sources_once_per_character(tmp_path):
    system = build_system(tmp_path)
    send(system, "一条完整消息")
    service = sealing(system)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(
                lambda _: service.seal("community", "first"),
                range(2),
            )
        )
    assert sum(segment is not None for segment in results) == 1
    with system.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_segments").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_sealing_rejects_other_community_and_nonmember(tmp_path):
    system = build_system(tmp_path)
    send(system, "有成员范围的消息")
    service = sealing(system)
    system.communities.create("另一个社群", "UTC", community_id="other")
    with pytest.raises(NotFoundError):
        service.seal("other", "first")
    system.characters.create("community", "xiaojin", character_id="outside")
    assert service.seal("community", "outside") is None


def test_sealing_material_budget_preserves_remaining_exact_sources(tmp_path):
    system = build_system(tmp_path)
    messages = tuple(send(system, f"第 {index} 条消息") for index in range(5))
    service = MemorySealing(
        system.database,
        InstanceRepository(),
        ConversationRepository(),
        system.world,
        SegmentRepository(),
        ThoughtRepository(),
        max_messages=2,
    )
    segments = tuple(service.seal("community", "first") for _ in range(3))
    assert tuple(len(message_ids(segment)) for segment in segments) == (2, 2, 1)
    assert tuple(source for segment in segments for source in message_ids(segment)) == tuple(
        message.message_id for message in messages
    )
    assert service.seal("community", "first") is None
