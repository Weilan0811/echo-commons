import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from support.agents import attach_execution
from support.memory import message_ids, sealing
from support.recovery import conversation_recovery
from support.reflection import build_reflection
from support.social import build_planning_system, send

from echo_commons.agents.contracts.output import CHARACTER_EXPRESSION_CONTRACT, expression_message
from echo_commons.agents.contracts.recovery import RecoveryAction
from echo_commons.execution.contracts import Disposition
from echo_commons.execution.recovery import QueuePolicy
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
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


def prepare_commit_system(tmp_path):
    system = build_planning_system(tmp_path)
    send(
        system,
        "小槿，你今天想一起做什么？请告诉我你的想法。",
        mentions=(ActorRef("character", "first"),),
    )
    system.planner.plan()
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


def test_tasks_prepare_with_current_contract_without_model_call(tmp_path):
    system = prepare_commit_system(tmp_path)
    try:
        snapshots = tuple(
            system.executor.prepare(task_id, attempt=1).invocation.context
            for task_id in system.task_ids
        )
        assert len(snapshots) == 1
        assert {item.scope.character_id for item in snapshots} == {"first"}
        assert all(item.schema_version == 2 and item.scope.conversations for item in snapshots)
        assert all(
            CHARACTER_EXPRESSION_CONTRACT in item.action_space.output_contracts
            for item in snapshots
        )
        recovery = system.queue.recovery.review("reply_target_unknown")
        assert recovery.action is RecoveryAction.RETRY_TASK
        assert "reply_to" in recovery.failure.repair_hint
        assert system.gateway._clients == {}
    finally:
        asyncio.run(system.gateway.close())


@pytest.mark.model
def test_real_results_commit_once_and_keep_second_snapshot_after_first_message(tmp_path):
    system = prepare_commit_system(tmp_path)

    async def run():
        try:
            receipts = []
            snapshots = {}
            generated_thoughts = {}
            for index in range(2):
                lease = await system.queue.claim(f"commit-test-{index}", datetime.now(UTC))
                assert lease
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
                thought = expression_message(result.output.payload).thought
                if thought.strip():
                    generated_thoughts[receipt.result_id] = thought
                system.planner.plan()
            return snapshots, receipts, generated_thoughts
        finally:
            await system.gateway.close()

    snapshots, receipts, generated_thoughts = asyncio.run(run())
    with system.database.read() as connection:
        for task, snapshot in snapshots.items():
            assert system.tasks.get(connection, task)["snapshot_json"] == snapshot
        messages = connection.execute(
            "SELECT * FROM messages WHERE sender_kind = 'character'"
        ).fetchall()
        assert len(messages) == 2
        assert {row["result_id"] for row in messages} == {receipt.result_id for receipt in receipts}
        assert {
            row["result_id"]: row["content"] for row in connection.execute("SELECT * FROM thoughts")
        } == generated_thoughts
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
                    message.role == "assistant" and thought.content in message.content
                    for message in prompt.messages
                )
            assert system.executor.prepare(task_id, attempt=1).invocation.context == context
    segments = {
        character: memory_sealing.seal("community", character) for character in ("first", "second")
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
            assert memory_sealing.seal("community", character) is None

    thought_sources = [
        (character, source.source_id)
        for character, segment in segments.items()
        for source in segment.sources
        if source.kind == "thought"
    ]
    if not generated_thoughts:
        assert thought_sources == []
        return
    assert len(thought_sources) == len(generated_thoughts)
    owner, thought_id = thought_sources[0]
    other = "second" if owner == "first" else "first"
    context, coordinator = build_reflection(system)
    run = coordinator.start_segment("community", owner, segments[owner].segment_id)
    with system.database.read() as connection:
        snapshot = RunRepository().snapshot(connection, "community", owner, str(run.graph_run_id))
        context.sources.check_sources(connection, snapshot)
    thoughts = ThoughtRepository()
    with system.database.transaction() as connection:
        with pytest.raises(NotFoundError):
            thoughts.clear_text(connection, "community", other, thought_id, datetime.now(UTC))
        assert thoughts.clear_text(connection, "community", owner, thought_id, datetime.now(UTC))
        assert not thoughts.clear_text(
            connection, "community", owner, thought_id, datetime.now(UTC)
        )
        cleared = thoughts.get(connection, "community", owner, thought_id)
        assert cleared["content"] is None and cleared["content_version"] == "1"
        assert cleared["segment_id"] == segments[owner].segment_id
        assert (
            thoughts.for_results(
                connection,
                "community",
                owner,
                (cleared["result_id"],),
                datetime.now(UTC),
            )
            == {}
        )
    with system.database.read() as connection:
        stored = RunRepository().snapshot(connection, "community", owner, str(run.graph_run_id))
        assert stored == snapshot
        with pytest.raises(ReflectionSourceUnavailable):
            context.sources.check_sources(connection, stored)
        with pytest.raises(ReflectionSourceUnavailable):
            context.prepare(
                connection, "community", owner, segments[owner].segment_id, datetime.now(UTC)
            )


@pytest.mark.model
def test_real_results_keep_original_audience_and_reject_departed_character(tmp_path):
    system = prepare_commit_system(tmp_path)

    async def run():
        try:
            first_lease = await system.queue.claim("audience-first", datetime.now(UTC))
            first = system.executor.prepare(first_lease.task_id, attempt=first_lease.attempt)
            result = await first.agent.run(first.invocation)
            old_bob = system.conversations.leave(
                "community", "conversation", ActorRef("player", "bob")
            )
            new_bob = system.conversations.join(
                "community", "conversation", ActorRef("player", "bob")
            )
            system.characters.create("community", "xiaojin", character_id="new-character")
            newcomer = system.conversations.join(
                "community", "conversation", ActorRef("character", "new-character")
            )
            approved = system.commit.commit(first_lease, first.invocation, result)
            assert approved.outcome.disposition is Disposition.COMPLETED and approved.message_id
            system.planner.plan()
            second_lease = await system.queue.claim("audience-second", datetime.now(UTC))
            second = system.executor.prepare(second_lease.task_id, attempt=second_lease.attempt)
            result = await second.agent.run(second.invocation)
            actor = ActorRef("character", second.invocation.scope.character_id)
            system.conversations.leave("community", "conversation", actor)
            rejoined = system.conversations.join("community", "conversation", actor)
            assert rejoined.membership_id != second.invocation.context.scope.membership_id
            expired = system.commit.commit(second_lease, second.invocation, result)
            assert expired.outcome.disposition is Disposition.IGNORED
            with system.database.read() as connection:
                message = system.messages.get(connection, "conversation", approved.message_id)
                assert old_bob.membership_id not in message.audience
                assert new_bob.membership_id not in message.audience
                assert newcomer.membership_id not in message.audience
                assert (
                    connection.execute(
                        "SELECT status FROM conversation_results WHERE result_id=?",
                        (expired.result_id,),
                    ).fetchone()[0]
                    == "expired"
                )
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM messages WHERE sender_kind='character'"
                    ).fetchone()[0]
                    == 1
                )
        finally:
            await system.gateway.close()

    asyncio.run(run())


@pytest.mark.model
@pytest.mark.parametrize("change", ["archive", "player_leave"])
def test_real_late_result_is_rejected_after_conversation_lifecycle_change(tmp_path, change):
    system = prepare_commit_system(tmp_path)

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
    assert result.status.value in ("completed", "no_proposal")
    if change == "archive":
        system.conversations.archive("community", "conversation")
    else:
        system.conversations.leave("community", "conversation", ActorRef("player", "alice"))
    receipt = system.commit.commit(lease, prepared.invocation, result)
    assert receipt.outcome.disposition is (
        Disposition.COMPLETED if change == "player_leave" else Disposition.IGNORED
    )
    with system.database.read() as connection:
        assert connection.execute(
            "SELECT status FROM conversation_results WHERE result_id=?", (receipt.result_id,)
        ).fetchone()[0] == ("approved" if change == "player_leave" else "expired")
        assert connection.execute(
            "SELECT COUNT(*) FROM messages WHERE sender_kind='character'"
        ).fetchone()[0] == (1 if change == "player_leave" and receipt.message_id else 0)
