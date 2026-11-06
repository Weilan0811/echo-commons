import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import tiktoken
from support.application import settings_for
from support.messages import build_system

from echo_commons.agents.contracts.context import ContextSnapshot, SnapshotScope
from echo_commons.agents.contracts.output import (
    CHARACTER_EXPRESSION_CONTRACT,
    CHARACTER_EXPRESSION_TYPE,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.agents.contracts.run import AgentOutput, AgentRunResult
from echo_commons.app.composition import assemble
from echo_commons.execution.recovery import decision
from echo_commons.infrastructure.models.budget import InputBudget
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.conversations.domain.message import Message, PlayerMessage
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.continuity import MemoryContinuity
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.shared.actors import ActorRef


def application(tmp_path):
    system = build_system(tmp_path)
    return assemble(
        settings_for(tmp_path, workers=False).model_copy(
            update={"database_path": str(system.database.path)}
        )
    )


def snapshot(app, character_id="first"):
    context = app.supervisor.workers["conversation-memory"].preparation.context
    with app.database.read() as connection:
        conversation = context.conversations.get(connection, "community", "conversation")
        member = context.conversations.current(
            connection, "conversation", ActorRef("character", character_id)
        )
        return context.prepare_for(
            connection,
            SnapshotScope(
                community_id="community",
                character_id=character_id,
                conversation_id="conversation",
                membership_id=member.membership_id,
                observation_upper_sequence=conversation.next_sequence - 1,
            ),
            member,
            (),
            datetime.now(UTC),
            membership_version=conversation.membership_version,
        )


def size(value):
    outputs = OutputRegistry()
    outputs.register(CHARACTER_EXPRESSION_CONTRACT, CHARACTER_EXPRESSION_TYPE)
    prompt = project_snapshot(value, output_contract=CHARACTER_EXPRESSION_CONTRACT, outputs=outputs)
    return value.memory.input_budget.measure(prompt.messages)


def pressure_application(tmp_path, app=None, character_id="first", *, ask=False):
    if app is None:
        app = application(tmp_path)
        # 通过实际消息存储准备上下文读取材料，待回应批次由独立的完整流程验证。
        with app.database.transaction() as connection:
            source = app.intake
            members = source.conversations.members(connection, "conversation")
            sender = source.conversations.current(
                connection, "conversation", ActorRef("player", "alice")
            )
            for index in range(24):
                now = datetime.now(UTC)
                message = Message(
                    str(uuid4()),
                    "community",
                    "conversation",
                    source.conversations.allocate_sequence(connection, "conversation", now),
                    ActorRef("player", "alice"),
                    sender.membership_id,
                    f"第{index}次交流：我们约定周末一起做饭，小红带蔬菜，小明带蛋糕。"
                    + "大家讨论了各自喜欢的口味，希望每个人都吃得开心。" * 5,
                    "conversation",
                    tuple(m.membership_id for m in members),
                    (),
                    None,
                    str(uuid4()),
                    None,
                    None,
                    str(uuid4()),
                    now,
                )
                source.messages.add(connection, message)
                source.indexer.message(connection, message)
    context = app.supervisor.workers["conversation-memory"].preparation.context
    full = snapshot(app, character_id)
    minimum = full.model_copy(
        update={
            "perspective": full.perspective.model_copy(update={"history": ()}),
            "memory": full.memory.model_copy(
                update={
                    "resident": (),
                    "recalled": (),
                    "segment_summaries": (),
                    "history_thoughts": (),
                    "session_digest": "",
                }
            ),
        }
    )
    context.input_budget = context.input_budget.model_copy(
        update={"max_chars": size(minimum) + 1800}
    )
    if ask:
        app.intake.send(
            "community",
            "conversation",
            PlayerMessage(
                "alice",
                "recall-question",
                "我们刚才在另一个群聊的周末安排是什么？",
                mentions=(ActorRef("character", character_id),),
            ),
        )
    task_id = app.conversation_initiations.request(
        "community",
        "conversation",
        character_id,
        "你准备回答眼前的问题。" if ask else "你想继续做饭的话题。",
        request_id="pressure",
    )
    return app, task_id


def test_budget_counts_protocol_tools_and_output_reservation():
    budget = InputBudget(
        model_entry_id="configured", context_window_tokens=1024, output_tokens=128, max_chars=10000
    )
    messages = (PromptMessage(role="user", content="你好" * 100),)
    assert budget.measure(messages) < budget.max_chars
    assert budget.measure(messages, ({"description": "工具说明" * 200},)) > budget.max_chars
    assert budget.model_copy(update={"output_tokens": 800}).measure(messages) > budget.max_chars
    encoded = budget.model_copy(update={"token_counter": "o200k_base"})
    assert encoded.count("一起做饭吧！") == len(
        tiktoken.get_encoding("o200k_base").encode("一起做饭吧！")
    )


def test_capacity_replaces_twenty_message_limit_and_carries_other_scene(tmp_path):
    app = application(tmp_path)
    actors = (
        ActorRef("player", "alice"),
        ActorRef("player", "bob"),
        ActorRef("character", "first"),
    )
    app.conversations.create("community", "group", actors, conversation_id="other")
    for index in range(25):
        app.intake.send(
            "community", "conversation", PlayerMessage("alice", str(index), f"讨论第{index}件事")
        )
    other = app.intake.send(
        "community", "other", PlayerMessage("alice", "nearby", "刚刚在公园遇到了小红。")
    )
    current = snapshot(app)
    assert sum(m.conversation_id == "conversation" for m in current.perspective.history) == 25
    assert other.message_id in {m.message_id for m in current.perspective.history}
    assert current.memory.input_budget.model_entry_id
    assert size(current) <= current.memory.input_budget.max_chars
    assert not app.gateway._clients


def test_pressure_waits_without_claim_and_restarts_with_original_cutoff(tmp_path):
    async def run():
        app, task_id = pressure_application(tmp_path)
        repository = ConversationTaskRepository()
        with app.database.read() as connection:
            original = repository.snapshot(connection, task_id)
            task = repository.get(connection, task_id)
            assert not original.memory.context_prepared, (
                task["status"],
                task["last_error_code"],
                original.memory.input_budget.max_chars,
                size(original),
                len(original.perspective.history),
                len(original.perspective.inputs),
            )
        assert await app.queue.claim("conversation", datetime.now(UTC)) is None
        assert await app.supervisor.workers["conversation-memory"].run_once()
        with app.database.read() as connection:
            segments = connection.execute("SELECT segment_id FROM memory_segments").fetchall()
            assert segments
            references = SegmentRepository().references(connection, segments[0][0])
            assert {s.source_id for s in references} <= {
                m.message_id for m in original.perspective.history
            }
            assert repository.get(connection, task_id)["attempt_count"] == 0
            graph_ids = tuple(
                r[0] for r in connection.execute("SELECT graph_run_id FROM reflection_graph_runs")
            )
        newer = app.intake.send(
            "community", "conversation", PlayerMessage("alice", "after", "稍后再聊。")
        )
        restarted = assemble(app.settings)
        assert not await restarted.supervisor.workers["conversation-memory"].run_once()
        with restarted.database.read() as connection:
            assert repository.snapshot(connection, task_id).scope == original.scope
            assert newer.message_id not in {
                m.message_id for m in repository.snapshot(connection, task_id).perspective.history
            }
            assert (
                tuple(
                    r[0]
                    for r in connection.execute("SELECT graph_run_id FROM reflection_graph_runs")
                )
                == graph_ids
            )
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        await app.gateway.close()
        await restarted.gateway.close()

    asyncio.run(run())


def test_nearby_scene_keeps_latest_and_relevant_older_message_within_capacity(tmp_path):
    app = application(tmp_path)
    app.conversations.create(
        "community",
        "group",
        (ActorRef("player", "alice"), ActorRef("player", "bob"), ActorRef("character", "first")),
        conversation_id="nearby",
    )
    relevant = app.intake.send(
        "community", "nearby", PlayerMessage("alice", "plan", "蓝风铃的集合安排是明天到旧码头。")
    )
    for index in range(24):
        latest = app.intake.send(
            "community",
            "nearby",
            PlayerMessage(
                "alice", f"unrelated-{index}", f"第{index}条近况：" + "晚餐聊了好多口味。" * 8
            ),
        )
    full = snapshot(app)
    minimum = full.model_copy(
        update={
            "perspective": full.perspective.model_copy(update={"history": ()}),
            "memory": full.memory.model_copy(
                update={
                    "resident": (),
                    "recalled": (),
                    "segment_summaries": (),
                    "history_thoughts": (),
                    "session_digest": "",
                }
            ),
        }
    )
    context = app.supervisor.workers["conversation-memory"].preparation.context
    context.input_budget = context.input_budget.model_copy(
        update={"max_chars": size(minimum) + 1000}
    )
    app.intake.send(
        "community", "conversation", PlayerMessage("alice", "question", "蓝风铃的集合安排是什么？")
    )
    task = app.conversation_initiations.request(
        "community", "conversation", "first", "你准备回答眼前的问题。", request_id="relevant"
    )
    with app.database.read() as connection:
        prepared = ConversationTaskRepository().snapshot(connection, task)
    ids = {m.message_id for m in prepared.perspective.history}
    assert relevant.message_id in ids and latest.message_id in ids
    assert len(ids) < 25
    assert size(prepared) <= prepared.memory.input_budget.max_chars


def test_failed_summary_preserves_waiting_sources_and_reuses_recovery(tmp_path):
    async def run():
        app, task_id = pressure_application(tmp_path)
        worker = app.supervisor.workers["conversation-memory"]
        await worker.run_once()
        lease = await app.reflection_queue.claim("reflection", datetime.now(UTC))
        assert lease is not None
        with app.database.read() as connection:
            graph_id = app.reflection_queue.nodes.get(connection, lease.task_id).graph_run_id
            original = ConversationTaskRepository().snapshot(connection, task_id)
            count = connection.execute("SELECT COUNT(*) FROM memory_segments").fetchone()[0]
        await app.reflection_queue.apply_recovery(
            lease,
            datetime.now(UTC),
            decision("provider_unavailable", FailureCategory.PROVIDER, RecoveryAction.FAIL),
        )
        await worker.run_once()
        with app.database.read() as connection:
            current = ConversationTaskRepository().snapshot(connection, task_id)
            assert current.perspective.history == original.perspective.history
            assert not current.memory.context_prepared
            assert ConversationTaskRepository().get(connection, task_id)["attempt_count"] == 0
            assert connection.execute("SELECT COUNT(*) FROM memory_segments").fetchone()[0] == count
        restarted = app.reflection.restart("community", "first", str(graph_id))
        assert str(restarted.graph_run_id) == str(graph_id)
        assert await app.reflection_queue.claim("resumed", datetime.now(UTC)) is not None
        await app.gateway.close()

    asyncio.run(run())


def test_old_snapshot_roundtrip_does_not_add_context_preparation_fields(tmp_path):
    app = application(tmp_path)
    value = snapshot(app).model_dump(mode="json")
    for field in (
        "input_budget",
        "current_ratio",
        "nearby_ratio",
        "context_prepared",
        "covered_message_ids",
        "summary_message_ids",
    ):
        value["memory"].pop(field, None)
    restored = ContextSnapshot.model_validate(value)
    assert restored.model_dump(mode="json") == value


@pytest.mark.parametrize("compressed", (False, True))
def test_cleared_thought_keeps_summary_coverage_under_context_pressure(tmp_path, compressed):
    app = application(tmp_path)
    for index in range(24):
        app.intake.send(
            "community",
            "conversation",
            PlayerMessage(
                "alice", str(index), f"第{index}次交流：" + "我们约定周末一起做饭。" * 10
            ),
        )
    context = app.supervisor.workers["conversation-memory"].preparation.context
    # 先用充足容量提交实际业务提议，再验证清除原文后的容量压力。
    context.input_budget = context.input_budget.model_copy(update={"max_chars": 32000})
    task_id = app.conversation_initiations.request(
        "community", "conversation", "first", "继续讨论周末安排。", request_id="with-thought"
    )
    lease = asyncio.run(app.queue.claim("summary-coverage", datetime.now(UTC)))
    assert lease is not None and lease.task_id == task_id
    invocation = app.handler.execution.prepare(task_id, attempt=lease.attempt).invocation
    result = AgentRunResult(
        invocation_id=invocation.identity.invocation_id,
        agent_id=invocation.identity.agent_id,
        agent_kind=invocation.identity.agent_kind,
        model_profile=invocation.execution_policy.model_profile,
        status="completed",
        stop_reason="proposal_ready",
        output=AgentOutput(
            contract=invocation.output_contract,
            payload=CharacterMessageProposal(
                thought="我想照顾大家的口味。", utterance="周末一起做饭吧，我来准备甜点。"
            ),
        ),
    )
    receipt = app.handler.commit.commit(lease, invocation, result)
    assert receipt.message_id is not None
    segment = app.memory_sealing.seal("community", "first")
    summary = "我们约定周末一起做饭，小红带蔬菜，小明带蛋糕，我准备甜点。"
    with app.database.transaction() as connection:
        MemoryIngestion(SegmentRepository(), CoverageRepository()).ingest(
            connection, "community", "first", segment.segment_id, summary, datetime.now(UTC)
        )
        thought_id = next(s.source_id for s in segment.sources if s.kind == "thought")
        assert ThoughtRepository().clear_text(
            connection, "community", "first", thought_id, datetime.now(UTC)
        )
    batches = app.reflection_workflow.batches
    if compressed:
        batch = batches.freeze("community", "first", SummaryConsumer.CONTINUITY)
        assert batch is not None
        with app.database.transaction() as connection:
            MemoryContinuity(batches.provenance).compress(
                connection, "community", "first", batch.batch_id, summary, datetime.now(UTC)
            )
    app, waiting = pressure_application(tmp_path, app)
    with app.database.read() as connection:
        prepared = ConversationTaskRepository().snapshot(connection, waiting)
        assert prepared.memory.context_prepared
        assert summary in (
            prepared.memory.session_digest
            if compressed
            else "\n".join(s.content for s in prepared.memory.segment_summaries)
        )
        assert size(prepared) <= prepared.memory.input_budget.max_chars
        assert len(prepared.perspective.history) < 24
        assert not prepared.memory.history_thoughts
        assert (
            batches.select(connection, "community", "first", SummaryConsumer.ORGANIZATION) is None
        )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.model
@pytest.mark.parametrize("character_id", ("first", "simple"))
def test_real_summary_unblocks_frozen_conversation_after_restart(tmp_path, character_id):
    async def run():
        app = application(tmp_path)
        try:
            if character_id == "simple":
                with app.database.read() as connection:
                    blueprint = app.characters.instances.get(
                        connection, "community", "first"
                    ).blueprint_id
                app.characters.create(
                    "community",
                    blueprint,
                    character_id=character_id,
                    player_id="alice",
                    memory_mode="simple",
                )
                app.conversations.join(
                    "community", "conversation", ActorRef("character", character_id)
                )
            for index in range(24):
                app.intake.send(
                    "community",
                    "conversation",
                    PlayerMessage(
                        "alice",
                        str(index),
                        f"第{index}次交流：我们约定周末一起做饭，小红带蔬菜，小明带蛋糕。"
                        + "大家讨论了各自喜欢的口味，希望每个人都吃得开心。" * 5,
                    ),
                )
            first = app.conversation_initiations.request(
                "community",
                "conversation",
                character_id,
                "回应大家的做饭安排。",
                request_id="before-pressure",
            )
            assert await app.supervisor.workers["conversations-0"].run_once()
            with app.database.read() as connection:
                assert ConversationTaskRepository().get(connection, first)["status"] == "completed"
            with app.database.read() as connection:
                actors = tuple(
                    m.actor
                    for m in app.conversations.conversations.members(connection, "conversation")
                )
            app.conversations.create("community", "group", actors, conversation_id="nearby")
            recent = app.intake.send(
                "community",
                "nearby",
                PlayerMessage("alice", "nearby-plan", "周末我们还约好了去公园看樱花。"),
            )
            app, task_id = pressure_application(tmp_path, app, character_id, ask=True)
            assert await app.supervisor.workers["conversation-memory"].run_once()
            await app.gateway.close()
            app = assemble(app.settings)
            for _ in range(40):
                await app.supervisor.workers["conversation-memory"].run_once()
                with app.database.read() as connection:
                    prepared = ConversationTaskRepository().snapshot(connection, task_id)
                    if prepared.memory.context_prepared:
                        break
                if not await app.supervisor.workers["reflection-0"].run_once():
                    await asyncio.sleep(0.1)
            else:
                pytest.fail("The real summary did not release the waiting conversation")
            assert prepared.memory.segment_summaries
            assert size(prepared) <= prepared.memory.input_budget.max_chars
            assert any("做饭" in s.content for s in prepared.memory.segment_summaries)
            assert recent.message_id in {m.message_id for m in prepared.perspective.history}
            lease = await app.queue.claim("conversation", datetime.now(UTC))
            assert lease is not None and lease.task_id == task_id
            result = await app.handler.execute(lease)
            with app.database.read() as connection:
                task = ConversationTaskRepository().get(connection, task_id)
                assert task["status"] == "completed", (result, dict(task))
                sent = connection.execute(
                    "SELECT m.text FROM messages m JOIN conversation_results r USING(result_id) "
                    "WHERE r.task_id=?",
                    (task_id,),
                ).fetchone()
                assert sent is not None
                assert any(word in sent[0] for word in ("公园", "樱花")), sent[0]
        finally:
            await app.gateway.close()

    asyncio.run(run())
