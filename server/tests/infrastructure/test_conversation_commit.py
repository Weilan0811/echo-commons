import asyncio
import shutil
from datetime import UTC, datetime, timedelta
from importlib.resources import files

import pytest
from historical_database import copy_to_historical_schema
from recovery_support import conversation_recovery
from test_agent_execution import attach_execution
from test_memory_sealing import message_ids, sealing
from test_reflection_context import build_reflection
from test_social_planning import build_planning_system, send

from echo_commons.execution.contracts import Disposition
from echo_commons.execution.recovery import QueuePolicy
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.conversations.repositories.results import ConversationResultRepository
from echo_commons.modules.conversations.tasks.commit import ConversationCommit
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.conversations.tasks.queue import ConversationQueue
from echo_commons.modules.conversations.tasks.review import ConversationReview, ReviewPolicy
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.reflection.contexts.sources import ReflectionSourceUnavailable
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.social.domain import ParticipationDecision, ParticipationStatus
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


def prepare_upgraded_legacy_commit_system(
    tmp_path, text="大家好！请各位说一句今天想一起做的事情。"
):
    system = build_planning_system(tmp_path)
    send(system, text)
    turn_id = system.planner.plan()[0]
    with system.database.transaction() as connection:
        turn = system.social.by_id(connection, turn_id)
        member = system.conversations.conversations.current(
            connection, "conversation", ActorRef("character", "second")
        )
        inputs = tuple(
            system.messages.get(connection, "conversation", message_id)
            for message_id in system.social.source_messages(connection, turn_id)
        )
        snapshot = system.planner.tasks.context.prepare(
            connection, turn, member, inputs, datetime.now(UTC)
        )
        system.social.decision(
            connection,
            ParticipationDecision(
                turn_id,
                "second",
                "selected_by_rule",
                1,
                ParticipationStatus.SELECTED,
                None,
                datetime.now(UTC),
            ),
        )
        system.tasks.prepare(connection, snapshot)
    old_sql = tmp_path / "version-nine-sql"
    old_sql.mkdir()
    for sql in files("echo_commons.infrastructure.database.sql").iterdir():
        if sql.name.endswith(".sql") and int(sql.name[:4]) <= 9:
            shutil.copyfile(str(sql), old_sql / sql.name)
    old = copy_to_historical_schema(system.database, old_sql, tmp_path / "upgraded.sqlite3")
    system.database.path = old.path
    assert initialize(system.database) == 17
    with system.database.read() as connection:
        system.task_ids = tuple(
            row[0] for row in connection.execute("SELECT task_id FROM conversation_tasks")
        )
    attach_execution(system, tmp_path)
    repository, results = ConversationQueueRepository(), ConversationResultRepository()
    policy = QueuePolicy()
    system.queue = ConversationQueue(
        system.database,
        repository,
        system.social,
        system.completion,
        policy,
        conversation_recovery(system, policy),
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
        system.queue.recovery,
        system.social_lifecycle,
    )
    return system


@pytest.mark.model
def test_real_results_commit_once_and_keep_second_snapshot_after_first_message(tmp_path):
    system = prepare_upgraded_legacy_commit_system(tmp_path)

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
    send(
        system,
        "继续刚才的话题。",
        mentions=tuple(ActorRef("character", identity) for identity in ("first", "second")),
    )
    system.planner.plan()
    with system.database.read() as connection:
        pending = tuple(
            row[0]
            for row in connection.execute(
                "SELECT task_id FROM conversation_tasks WHERE status = 'pending'"
            )
        )
        assert len(pending) == 1
        for task_id in pending:
            prepared = system.executor.prepare(task_id, attempt=1)
            character_id = prepared.invocation.scope.character_id
            context = prepared.invocation.context
            own = {
                row["thought_id"]: row
                for row in connection.execute(
                    "SELECT * FROM thoughts WHERE character_id = ?", (character_id,)
                )
            }
            assert {thought.thought_id for thought in context.memory.history_thoughts} == set(own)
            prompt = project_snapshot(
                context, output_contract=prepared.invocation.output_contract, outputs=system.outputs
            )
            for thought in context.memory.history_thoughts:
                assert thought.content == own[thought.thought_id]["content"]
                assert any(
                    message.role == "assistant" and '"thought":' in message.content
                    for message in prompt.messages
                )
            assert system.executor.prepare(task_id, attempt=1).invocation.context == context
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
            assert len(message_ids(segment)) == 4
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
        assert (
            thoughts.for_results(
                connection,
                "community",
                "first",
                "conversation",
                (cleared["result_id"],),
                datetime.now(UTC),
            )
            == {}
        )
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
    system = prepare_upgraded_legacy_commit_system(tmp_path)

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


@pytest.mark.model
@pytest.mark.parametrize("change", ["archive", "player_leave"])
def test_real_late_result_is_rejected_after_conversation_lifecycle_change(tmp_path, change):
    system = prepare_upgraded_legacy_commit_system(
        tmp_path, "小槿，我第一次来这里，能请你给我推荐一种你喜欢的茶吗？"
    )

    async def generate():
        try:
            lease = await system.queue.claim("u08-late-result", datetime.now(UTC))
            assert lease is not None
            prepared = system.executor.prepare(lease.task_id, attempt=lease.attempt)
            result = await prepared.agent.run(prepared.invocation)
            return lease, prepared, result
        finally:
            await system.gateway.close()

    lease, prepared, result = asyncio.run(generate())
    assert result.status.value == "completed"
    if change == "archive":
        system.conversations.archive("community", "conversation")
    else:
        system.conversations.leave("community", "conversation", ActorRef("player", "alice"))
    receipt = system.commit.commit(lease, prepared.invocation, result)
    assert receipt.outcome.disposition is Disposition.IGNORED
    with system.database.read() as connection:
        assert connection.execute(
            "SELECT status FROM conversation_results WHERE result_id=?", (receipt.result_id,)
        ).fetchone()[0] == "expired"
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE sender_kind='character'"
        ).fetchone()[0] == 0
