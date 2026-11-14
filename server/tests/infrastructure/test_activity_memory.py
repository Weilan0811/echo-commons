import json
from pathlib import Path
from uuid import uuid4

import pytest
from echo_games.public import LeaveGameCommand, ResignGameCommand
from fastapi.testclient import TestClient
from support.activities import activity_game, message, prepare
from support.activity_actions import task_row
from support.application import settings_for
from support.games import create, operation
from support.http import create_group

from echo_commons.agents.contracts.activity import ActivityUnderstanding, MessageUnderstanding
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.execution.errors import ExecutionDeferred
from echo_commons.modules.communities.contracts import (
    EndGameActivityCommand,
    JoinGameSessionCommand,
)
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.services.continuity import MemoryContinuity
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.memory.services.retrieval import SearchScope
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError

ALICE = ActorRef("player", "alice")
CHARACTER = ActorRef("character", "first")


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as value:
        yield value


def context(app, game):
    with app.database.read() as connection:
        return app.game_queries.participant_context(connection, "community", CHARACTER, game)


def end(app, game):
    current = context(app, game)
    with app.database.read() as connection:
        conversation = app.conversations.conversations.get(
            connection, "community", current.conversation_id
        )
    return app.game_participation.end_activity(
        ALICE,
        EndGameActivityCommand(
            game_id=game,
            request_id=uuid4().hex,
            expected_state_version=current.game.state_version,
            expected_conversation_version=conversation.state_version,
        ),
    )


def ingest(app, segment, text):
    with app.database.transaction() as connection:
        MemoryIngestion(app.segment_context.segments, CoverageRepository()).ingest(
            connection, "community", "first", segment.segment_id, text, utc_now()
        )


def test_no_chat_sources_wait_for_idle_and_result_keeps_postgame_open(client):
    game = activity_game(client)
    app = client.app.state.application
    with app.database.transaction() as connection:
        assert app.memory_sealing.freeze(connection, "community", "first", automatic=True) is None
    first = app.memory_sealing.seal("community", "first")
    assert first.activity_participation_id == context(app, game).access.participation_id
    assert first.sources and all(s.kind == "game_event" for s in first.sources)
    with app.database.read() as connection:
        materials = app.segment_context.materials(
            connection, "community", "first", first.segment_id
        )
        snapshot = app.segment_context.prepare(
            connection, "community", "first", first.segment_id, utc_now()
        )
        app.segment_context.sources.check_sources(connection, snapshot)
        assert snapshot.summary_task.purpose == "segment"
        assert snapshot.summary_task.activity_ranges[0].closed_at_utc is None
        assert all(m.kind == "game_event" for m in materials)
        with pytest.raises(NotFoundError):
            app.segment_context.perspective.activities.event(
                connection, "community", "second", materials[0].source_id, utc_now()
            )
    current = context(app, game)
    with app.database.read() as connection:
        alice = app.game_participation.seat_access(connection, ALICE, game)
    app.game_participation.resign_game(
        ALICE,
        ResignGameCommand(
            game_id=game,
            request_id="resign",
            expected_state_version=current.game.state_version,
            participation_id=alice.participation_id,
        ),
    )
    postgame = message(client, game, "这次封堵很漂亮，下回再来。")
    with app.database.transaction() as connection:
        experiences = app.memory_sealing.activity_experiences
        experiences.sync(connection, "community", "first", utc_now())
        assert (
            connection.execute("SELECT closed_at_utc FROM memory_activity_episodes").fetchone()[0]
            is None
        )
    end(app, game)
    final = app.memory_sealing.seal("community", "first")
    assert postgame.message_id in {s.source_id for s in final.sources}
    assert final.activity_participation_id == first.activity_participation_id
    assert app.memory_sealing.seal("community", "first") is None
    with app.database.read() as connection:
        episode = connection.execute("SELECT * FROM memory_activity_episodes").fetchone()
        assert episode["closed_at_utc"] and episode["materials_complete"]
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_whole_episode_reuses_stage_coverage_and_is_searchable_after_restart(client):
    game = activity_game(client)
    app = client.app.state.application
    first = app.memory_sealing.seal("community", "first")
    ingest(app, first, "我和alice下五子棋，开局在中心交锋。")
    batches = app.reflection_workflow.batches
    stage = batches.freeze("community", "first", SummaryConsumer.CONTINUITY)
    with app.database.read() as connection:
        stage_context = app.reflection.summaries.prepare(
            connection,
            "community",
            "first",
            stage.batch_id,
            ReflectionGraphKind.CONTINUITY_COMPRESS,
            utc_now(),
        )
        assert stage_context.summary_task.purpose == "continuity"
        assert stage_context.summary_task.activity_ranges[0].closed_at_utc is None
    with app.database.transaction() as connection:
        MemoryContinuity(batches.provenance).compress(
            connection,
            "community",
            "first",
            stage.batch_id,
            "我和alice下棋，开局围绕中心交锋。",
            utc_now(),
        )
    message(client, game, "今天就到这里，改天再下。")
    end(app, game)
    last = app.memory_sealing.seal("community", "first")
    ingest(app, last, "活动提前结束，alice说改天再下。")
    final = batches.freeze("community", "first", SummaryConsumer.CONTINUITY)
    with app.database.read() as connection:
        final_context = app.reflection.summaries.prepare(
            connection,
            "community",
            "first",
            final.batch_id,
            ReflectionGraphKind.CONTINUITY_COMPRESS,
            utc_now(),
        )
        assert final_context.summary_task.purpose == "complete_experience"
        assert final_context.summary_task.activity_ranges[0].closed_at_utc is not None
        assert any("改天再下" in material.content for material in final_context.materials)
        earlier_context = app.reflection.summaries.prepare(
            connection,
            "community",
            "first",
            stage.batch_id,
            ReflectionGraphKind.CONTINUITY_COMPRESS,
            utc_now(),
        )
        assert earlier_context.summary_task == stage_context.summary_task
    assert final.previous_digest_ids
    assert final.sources[0].segment_id == last.segment_id
    with app.database.transaction() as connection:
        MemoryContinuity(batches.provenance).compress(
            connection,
            "community",
            "first",
            final.batch_id,
            "我和alice围绕中心下棋，随后提前结束，约好改天再下。",
            utc_now(),
        )
    assert app.memory_sealing.seal("community", "first") is None
    with app.database.transaction() as connection:
        batches.complete_episodes(connection, "community", "first")
        identity = connection.execute(
            "SELECT summary_digest_id FROM memory_activity_episodes"
        ).fetchone()[0]
        assert identity
        before = connection.total_changes
        batches.complete_episodes(connection, "community", "first")
        assert connection.total_changes == before
        hits = app.activity_context.conversation.retrieval.search(
            connection, SearchScope("community", "first", utc_now()), "alice 改天", limit=10
        )
        assert any(h.source_kind == "conversation_digest" and h.source_id == identity for h in hits)
        assert not any(h.source_kind == "game_event" for h in hits)
        assert connection.execute("SELECT count(*) FROM memory_source_coverage").fetchone()[
            0
        ] == len(first.sources) + len(last.sources)


def test_leave_and_rejoin_form_distinct_experiences_and_do_not_extend_old_sources(client):
    create_group(client, memory_mode="simple")
    game = create(client)[0]["game_id"]
    app = client.app.state.application
    operation(
        client,
        game,
        "participants",
        seat_id="white",
        participant={"kind": "character", "character_id": "first"},
    )
    previous = context(app, game)
    visible = message(client, game, "加入后的第一句。")
    app.game_participation.leave_game(
        ALICE,
        LeaveGameCommand(
            game_id=game,
            request_id="leave",
            expected_state_version=previous.game.state_version,
            participation_id=previous.access.participation_id,
        ),
    )
    hidden = message(client, game, "离开后讨论的内容。")
    app.game_participation.join_game(
        ALICE,
        JoinGameSessionCommand(
            game_id=game,
            request_id="rejoin",
            expected_state_version=3,
            seat_id="white",
            participant=CHARACTER,
        ),
    )
    later = message(client, game, "重新加入后的第一句。")
    one = app.memory_sealing.seal("community", "first")
    two = app.memory_sealing.seal("community", "first")
    assert one.activity_participation_id != two.activity_participation_id
    assert visible.message_id in {s.source_id for s in one.sources}
    assert later.message_id not in {s.source_id for s in one.sources}
    assert later.message_id in {s.source_id for s in two.sources}
    assert hidden.message_id not in {s.source_id for s in (*one.sources, *two.sources)}
    with app.database.read() as connection:
        experiences = app.memory_sealing.activity_experiences.activities
        for segment in (one, two):
            frame = experiences.read(
                connection, "community", "first", segment.activity_participation_id, utc_now()
            )
            own = [p for p in frame.session_context.participants if p.is_self]
            assert len(own) == 1
            assert own[0].participation_id == segment.activity_participation_id
            assert own[0].seat_id == "white"


def test_game_card_assigns_actual_winner_to_its_participant(client):
    game = activity_game(client)
    app = client.app.state.application
    current = context(app, game)
    with app.database.read() as connection:
        alice = app.game_participation.seat_access(connection, ALICE, game)
    app.game_participation.resign_game(
        ALICE,
        ResignGameCommand(
            game_id=game,
            request_id="winner",
            expected_state_version=current.game.state_version,
            participation_id=alice.participation_id,
        ),
    )
    with app.database.read() as connection:
        card = app.memory_sealing.activity_experiences.recent(
            connection, "community", "first", utc_now()
        )[0]
    content = json.loads(card.content)
    assert content["本人席位"] == "white"
    assert len(content["获胜者"]) == 1
    winner = content["获胜者"][0]
    assert winner["actor"] == {"kind": "character", "actor_id": "first"}
    assert winner["participation_id"] == card.memory_id and winner["is_self"]
    assert winner["seat_id"] == content["结果"]["winner_seat_id"]
    segment = app.memory_sealing.seal("community", "first")
    with app.database.read() as connection:
        graph = app.segment_context.prepare(
            connection, "community", "first", segment.segment_id, utc_now()
        )
        app.segment_context.sources.check_sources(connection, graph)
    assert graph.activity_sessions[0].winners[0].actor == CHARACTER


def test_activity_waits_for_history_summary_without_spending_a_model_attempt(client):
    game = activity_game(client)
    app = client.app.state.application
    app.activity_context.policy = app.activity_context.policy.model_copy(
        update={"input_max_chars": 48000}
    )
    app.activity_context.input_budgets = {
        kind: budget.model_copy(update={"max_chars": 48000})
        for kind, budget in app.activity_context.input_budgets.items()
    }
    for index in range(12):
        message(client, game, f"第{index}段交流：" + "我们讨论刚才的封堵和下一步选择。" * 70)
    previous = prepare(client, game, input_id="history")
    app.activity_context.record_understanding(
        "community",
        "first",
        "history",
        ActivityUnderstanding(
            messages=tuple(
                MessageUnderstanding(message_id=m.message_id, interpretation="讨论本局行棋")
                for m in previous.material.conversation.perspective.inputs
            ),
            event_ids=tuple(e.event_id for e in previous.material.game.events),
        ),
    )
    current = message(client, game, "轮到你了。")
    sealed = app.memory_sealing.seal("community", "first")
    assert current.message_id in {source.source_id for source in sealed.sources}
    app.activity_context.policy = app.activity_context.policy.model_copy(
        update={"input_max_chars": 30000}
    )
    app.activity_coordinator.scan()
    lease = client.portal.call(app.activity_queue.claim, "prepare", utc_now())
    with pytest.raises(ExecutionDeferred) as error:
        client.portal.call(app.activity_execution.execute, lease)
    assert error.value.code == "memory_summary_pending"
    recovery = app.activity_queue.recovery.classify(error.value)
    client.portal.call(app.activity_queue.apply_recovery, lease, utc_now(), recovery)
    assert task_row(app, lease.task_id)["attempt_count"] == 0
    assert client.portal.call(app.activity_queue.claim, "blocked", utc_now()) is None
    with app.database.read() as connection:
        row = connection.execute("SELECT * FROM memory_segments").fetchone()
        segment = app.segment_context.segments.get(
            connection, "community", "first", row["segment_id"]
        )
    # 人工摘要通过正式存储入口提交；模型生成由独立的真实模型用例验证。
    ingest(app, segment, "我和alice讨论了刚才的封堵，以及下一步的行棋选择。")
    assert client.portal.call(app.supervisor.workers["activity-memory"].run_once)
    resumed = client.portal.call(app.activity_queue.claim, "resumed", utc_now())
    assert resumed.task_id == lease.task_id and resumed.attempt == 1


@pytest.mark.model
@pytest.mark.parametrize("local", [False, True], ids=["ordinary", "local"])
def test_real_no_chat_activity_thought_enters_existing_reflection_and_long_term_pipeline(
    tmp_path, local
):
    settings = settings_for(tmp_path, workers=False)
    if local:
        registry = tmp_path / "models.toml"
        registry.write_text(
            Path(settings.model_registry_path)
            .read_text(encoding="utf-8")
            .replace("[decision]\nenabled = false", "[decision]\nenabled = true"),
            encoding="utf-8",
        )
        settings = settings.model_copy(update={"model_registry_path": str(registry)})
    with TestClient(create_app(settings)) as client:
        game = activity_game(client, memory_mode="full")
        app = client.app.state.application
        app.activity_coordinator.scan()
        lease = client.portal.call(app.activity_queue.claim, "memory-activity", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        app.activity_commit.commit(lease, artifact)
        end(app, game)
        run = app.reflection_workflow.freeze_segment(app.memory_sealing, "community", "first")
        assert run is not None
        with app.database.read() as connection:
            segment = connection.execute("SELECT * FROM memory_segments").fetchone()
            materials = app.segment_context.materials(
                connection, "community", "first", segment["segment_id"]
            )
            if artifact["mode"] == "decision":
                assert not any(m.kind == "thought" for m in materials)
            else:
                assert any(m.kind == "thought" for m in materials)
            assert any(m.kind == "game_event" for m in materials)
        dispatcher = app.supervisor.workers["tasks-0"].dispatcher

        def execute_graph(graph):
            for _ in range(10):
                lease = client.portal.call(app.reflection_queue.claim, dispatcher.owner, utc_now())
                assert lease is not None
                client.portal.call(dispatcher._execute, lease)
                with app.database.read() as connection:
                    current = app.reflection.runs.get(
                        connection, "community", "first", str(graph.graph_run_id)
                    )
                if current.is_terminal:
                    assert current.status == "completed"
                    return
            pytest.fail("Reflection did not complete within its defined nodes")

        execute_graph(run)
        final = app.reflection_workflow.schedule_summaries(
            "community", "first", SummaryConsumer.CONTINUITY
        )
        execute_graph(final)
        organize = app.reflection_workflow.schedule_summaries(
            "community", "first", SummaryConsumer.ORGANIZATION
        )
        execute_graph(organize)
        assert app.memory_sealing.seal("community", "first") is None
        with app.database.transaction() as connection:
            app.summary_batches.complete_episodes(connection, "community", "first")
            assert connection.execute(
                "SELECT summary_digest_id FROM memory_activity_episodes"
            ).fetchone()[0]
        with app.database.read() as connection:
            assert connection.execute("SELECT summary_text FROM memory_segments").fetchone()[0]
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
