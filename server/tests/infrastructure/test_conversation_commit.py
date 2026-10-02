import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from test_agent_execution import attach_execution
from test_memory_sealing import message_ids, sealing
from test_reflection_context import build_reflection
from test_social_planning import build_planning_system, send

from echo_commons.execution.contracts import Disposition
from echo_commons.execution.recovery import QueuePolicy
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.conversations.repositories.results import ConversationResultRepository
from echo_commons.modules.conversations.tasks.commit import ConversationCommit
from echo_commons.modules.conversations.tasks.queue import ConversationQueue
from echo_commons.modules.conversations.tasks.review import ConversationReview, ReviewPolicy
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.reflection.contexts.sources import ReflectionSourceUnavailable
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


def prepare_commit_system(tmp_path):
    system = build_planning_system(tmp_path)
    send(system, "大家好！请各位说一句今天想一起做的事情。")
    system.planner.plan()
    with system.database.read() as connection:
        system.task_ids = tuple(
            row[0] for row in connection.execute("SELECT task_id FROM conversation_tasks")
        )
    attach_execution(system, tmp_path)
    repository, results = ConversationQueueRepository(), ConversationResultRepository()
    policy = QueuePolicy()
    system.queue = ConversationQueue(
        system.database, repository, system.social, system.completion, policy
    )
    system.commit = ConversationCommit(
        system.database,
        system.tasks,
        repository,
        results,
        ConversationReview(
            CommunityRepository(),
            InstanceRepository(),
            system.conversations.conversations,
            system.messages,
            system.perspective,
            ReviewPolicy(),
        ),
        CommunityRepository(),
        system.conversations.conversations,
        system.messages,
        system.intake.batches,
        system.index,
        ThoughtRepository(),
        system.social,
        system.completion,
        policy,
    )
    return system


@pytest.mark.model
def test_real_results_commit_once_and_keep_second_snapshot_after_first_message(tmp_path):
    system = prepare_commit_system(tmp_path)

    async def run():
        try:
            leases = []
            while lease := await system.queue.claim("commit-test", datetime.now(UTC)):
                if lease.task_id in system.task_ids:
                    leases.append(lease)
            assert len(leases) == 2
            receipts = []
            snapshots = {}
            for lease in leases:
                prepared = system.executor.prepare(
                    lease.task_id,
                    attempt=lease.attempt,
                    deadline_utc=datetime.now(UTC) + timedelta(seconds=80),
                )
                snapshots[lease.task_id] = prepared.invocation.context.model_dump_json()
                result = await prepared.agent.run(prepared.invocation)
                receipt = system.commit.commit(lease, prepared.invocation, result)
                assert receipt.outcome.disposition is Disposition.COMPLETED
                assert receipt.message_id is not None
                duplicate = system.commit.commit(lease, prepared.invocation, result)
                assert duplicate.result_id == receipt.result_id
                assert duplicate.outcome.disposition is Disposition.IGNORED
                receipts.append(receipt)
            return snapshots, receipts
        finally:
            await system.gateway.close()

    snapshots, receipts = asyncio.run(run())
    with system.database.read() as connection:
        for task, snapshot in snapshots.items():
            assert system.tasks.get(connection, task)["snapshot_json"] == snapshot
        messages = connection.execute(
            "SELECT * FROM messages WHERE sender_kind = 'character'"
        ).fetchall()
        assert len(messages) == 2
        assert {row["result_id"] for row in messages} == {receipt.result_id for receipt in receipts}
        assert connection.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM input_batches WHERE sender_kind = 'character' "
                "AND status = 'sealed'"
            ).fetchone()[0]
            == 2
        )
        for receipt in receipts:
            stored = connection.execute(
                "SELECT payload_json FROM conversation_results WHERE result_id = ?",
                (receipt.result_id,),
            ).fetchone()[0]
            assert '"thought"' not in stored
        turn = connection.execute(
            "SELECT status FROM social_turns WHERE conversation_id = 'conversation'"
        ).fetchone()
        assert turn[0] == "completed"

    memory_sealing = sealing(system)
    segments = {
        character: memory_sealing.seal("community", character, "conversation")
        for character in ("first", "second")
    }
    with system.database.read() as connection:
        for character, segment in segments.items():
            own_thought_ids = {
                row[0]
                for row in connection.execute(
                    "SELECT thought_id FROM thoughts WHERE character_id = ?",
                    (character,),
                )
            }
            assert {source.source_id for source in segment.sources if source.kind == "thought"} == (
                own_thought_ids
            )
            assert len(message_ids(segment)) == 3
            assert memory_sealing.seal("community", character, "conversation") is None

    context, coordinator = build_reflection(system)
    run = coordinator.start_segment("community", "first", segments["first"].segment_id)
    with system.database.read() as connection:
        snapshot = RunRepository().snapshot(connection, "community", "first", str(run.graph_run_id))
        context.sources.check_sources(connection, snapshot)
    thought_id = next(
        source.source_id for source in segments["first"].sources if source.kind == "thought"
    )
    thoughts = ThoughtRepository()
    with system.database.transaction() as connection:
        with pytest.raises(NotFoundError):
            thoughts.clear_text(connection, "community", "second", thought_id, datetime.now(UTC))
        assert thoughts.clear_text(connection, "community", "first", thought_id, datetime.now(UTC))
        assert not thoughts.clear_text(
            connection, "community", "first", thought_id, datetime.now(UTC)
        )
        cleared = thoughts.get(connection, "community", "first", thought_id)
        assert cleared["content"] is None and cleared["content_version"] == "1"
        assert cleared["segment_id"] == segments["first"].segment_id
    with system.database.read() as connection:
        stored = RunRepository().snapshot(connection, "community", "first", str(run.graph_run_id))
        assert stored == snapshot
        with pytest.raises(ReflectionSourceUnavailable):
            context.sources.check_sources(connection, stored)
        with pytest.raises(ReflectionSourceUnavailable):
            context.prepare(
                connection, "community", "first", segments["first"].segment_id, datetime.now(UTC)
            )


@pytest.mark.model
def test_real_results_keep_original_audience_and_reject_departed_character(tmp_path):
    system = prepare_commit_system(tmp_path)

    async def generate():
        try:
            leases = []
            while lease := await system.queue.claim("audience-test", datetime.now(UTC)):
                leases.append(lease)
            prepared = tuple(
                system.executor.prepare(lease.task_id, attempt=lease.attempt) for lease in leases
            )
            results = await asyncio.gather(*(item.agent.run(item.invocation) for item in prepared))
            return leases, prepared, results
        finally:
            await system.gateway.close()

    leases, prepared, results = asyncio.run(generate())
    assert len(leases) == 2
    old_bob = system.conversations.leave("community", "conversation", ActorRef("player", "bob"))
    new_bob = system.conversations.join("community", "conversation", ActorRef("player", "bob"))
    system.characters.create("community", "xiaojin", character_id="new-character")
    newcomer = system.conversations.join(
        "community", "conversation", ActorRef("character", "new-character")
    )
    approved = system.commit.commit(leases[0], prepared[0].invocation, results[0])
    assert approved.outcome.disposition is Disposition.COMPLETED
    system.conversations.leave(
        "community",
        "conversation",
        ActorRef("character", prepared[1].invocation.scope.character_id),
    )
    rejoined = system.conversations.join(
        "community",
        "conversation",
        ActorRef("character", prepared[1].invocation.scope.character_id),
    )
    assert rejoined.membership_id != prepared[1].invocation.context.scope.membership_id
    expired = system.commit.commit(leases[1], prepared[1].invocation, results[1])
    assert expired.outcome.disposition is Disposition.IGNORED
    with system.database.read() as connection:
        message = system.messages.get(connection, "conversation", approved.message_id)
        assert old_bob.membership_id not in message.audience
        assert new_bob.membership_id not in message.audience
        assert newcomer.membership_id not in message.audience
        assert (
            connection.execute(
                "SELECT status FROM conversation_results WHERE result_id = ?", (expired.result_id,)
            ).fetchone()[0]
            == "expired"
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM messages WHERE sender_kind = 'character'"
            ).fetchone()[0]
            == 1
        )
        assert connection.execute("SELECT status FROM social_turns").fetchone()[0] == "completed"
