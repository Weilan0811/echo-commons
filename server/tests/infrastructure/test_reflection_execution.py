import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.encoders import jsonable_encoder
from historical_messages import historical_message
from test_application_lifecycle import settings_for

from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.agents.contracts.run import AgentRunStatus
from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.execution.contracts import Disposition
from echo_commons.execution.lease import LeaseLostError, with_heartbeat
from echo_commons.execution.recovery import decision
from echo_commons.modules.characters.domain.authoring import AuthoringContent
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.reflection.contracts.candidates import SegmentSummaryAction
from echo_commons.modules.reflection.domain.graph import (
    ReflectionExecutionKind,
    ReflectionGraphKind,
)
from echo_commons.shared.actors import ActorRef


def seed(application):
    application.communities.create("晚餐小组", "Asia/Shanghai", community_id="community")
    application.communities.update("community", expected_version=0, status="active")
    application.communities.register_player("玩家", player_id="player")
    application.communities.join("community", ActorRef("player", "player"))
    template = application.characters.catalog.catalog.blueprint("xiaojin")
    content = AuthoringContent(
        display_name=template.display_name,
        description="基础资料。",
        profile=template.profile.content,
        voice=template.voice.content,
        relational_dynamics=template.relational_dynamics.content,
    )
    draft, _ = application.authoring.create("player", "reflection-persona", content)
    draft = application.authoring.confirm_stage(
        "player", draft["draft_id"], draft["revision"], "basic"
    )
    draft = application.authoring.confirm_documents("player", draft["draft_id"], draft["revision"])
    blueprint, _ = application.authoring.confirm("player", draft["draft_id"], draft["revision"])
    for character in ("first", "second"):
        application.characters.create(
            "community",
            blueprint["blueprint_id"],
            player_id="player",
            character_id=character,
            memory_mode="full",
        )
    application.conversations.create(
        "community",
        "group",
        (
            ActorRef("player", "player"),
            ActorRef("character", "first"),
            ActorRef("character", "second"),
        ),
        conversation_id="conversation",
    )
    for character, secret in (("first", "草莓417"), ("second", "香蕉918")):
        historical_message(
            application,
            f"请记住晚餐暗号{secret}，只有你和我知道。",
            player="player",
            client=f"private-{character}",
            recipients=(ActorRef("character", character),),
        )
    application.intake.send(
        "community",
        "conversation",
        PlayerMessage(
            "player",
            "public",
            "我们现在已经开始一起准备晚餐。大家正愉快地协作做饭。"
            "我负责买菜，请你们帮忙准备米饭和蔬菜。记住现在的活动安排。",
            mentions=(ActorRef("character", "first"), ActorRef("character", "second")),
        ),
    )
    for character in ("first", "second"):
        segment = application.memory_sealing.seal("community", character)
        application.reflection.start_segment("community", character, segment.segment_id)


def test_prepared_reflection_uses_original_snapshot_and_current_lease(tmp_path):
    async def run():
        async with application_lifecycle(settings_for(tmp_path, workers=False)) as application:
            seed(application)
            lease = await application.reflection_queue.claim("reflection-worker", datetime.now(UTC))
            first = application.reflection_execution.prepare(lease.task_id, attempt=lease.attempt)
            second = application.reflection_execution.prepare(lease.task_id, attempt=lease.attempt)
            assert first.invocation.context == second.invocation.context
            assert (
                first.invocation.context.scope.character_id == first.invocation.scope.character_id
            )
            assert first.invocation.execution_policy.model_profile == "light"
            assert application.gateway._clients == {}
            assert await application.reflection_queue.apply_recovery(
                lease,
                datetime.now(UTC),
                decision("execution_cancelled", FailureCategory.HARNESS, RecoveryAction.FAIL),
            )
            with pytest.raises(LeaseLostError):
                await first.agent.run(first.invocation)
            assert application.gateway._clients == {}

    asyncio.run(run())


@pytest.mark.model
def test_two_characters_reflect_real_private_materials(tmp_path):
    async def run():
        settings = settings_for(tmp_path, workers=False).model_copy(
            update={"debug_capture_enabled": True, "debug_capture_path": str(tmp_path / "capture")}
        )
        async with application_lifecycle(settings) as application:
            seed(application)
            leases = tuple(
                [
                    await application.reflection_queue.claim(
                        f"reflection-{index}", datetime.now(UTC)
                    )
                    for index in range(2)
                ]
            )
            prepared = tuple(
                application.reflection_execution.prepare(
                    lease.task_id,
                    attempt=lease.attempt,
                    deadline_utc=datetime.now(UTC) + timedelta(seconds=300),
                )
                for lease in leases
            )
            results = await asyncio.gather(
                *(
                    with_heartbeat(
                        application.reflection_queue, lease, item.agent.run(item.invocation), 10
                    )
                    for lease, item in zip(leases, prepared, strict=True)
                )
            )
            assert {item.invocation.scope.character_id for item in prepared} == {"first", "second"}
            restart_targets = set()
            for item, result in zip(prepared, results, strict=True):
                assert result.status is AgentRunStatus.COMPLETED
                assert result.model_profile == "light"
                assert isinstance(result.output.payload, SegmentSummaryAction)
                character = item.invocation.scope.character_id
                own = "草莓417" if character == "first" else "香蕉918"
                other = "香蕉918" if character == "first" else "草莓417"
                serialized = item.invocation.context.model_dump_json()
                assert own in serialized and other not in serialized
                assert other not in result.output.payload.summary
                assert result.usage_summary.model_request_count >= 1
                again = application.reflection_execution.prepare(
                    item.invocation.scope.task_id, attempt=1
                )
                assert again.invocation.context == item.invocation.context
                lease = next(
                    lease for lease in leases if lease.task_id == item.invocation.scope.task_id
                )
                artifact = application.reflection_commit.commit(
                    lease, item.invocation, result, datetime.now(UTC)
                )
                restart_targets.add(artifact.graph_run_id)
                duplicate = application.reflection_commit.commit(
                    lease, item.invocation, result, datetime.now(UTC)
                )
                assert artifact == duplicate
                with application.database.read() as connection:
                    nodes = application.reflection_queue.nodes.for_graph(
                        connection, str(artifact.graph_run_id)
                    )
                    root = next(node for node in nodes if node.task_id == artifact.node_task_id)
                    assert root.status == "completed"
                    assert root.artifact_id == artifact.artifact_id
                    for node in nodes:
                        if node.node_key in ("relationship_reflect", "state_reflect"):
                            assert node.status == "skipped" or node.input_artifact_refs == (
                                artifact.reference,
                            )

            restarted_graphs = set()

            async def finish(lease):
                with application.database.read() as connection:
                    node = application.reflection_queue.nodes.get(connection, lease.task_id)
                with application.database.read() as connection:
                    graph = application.reflection_queue.run_for(connection, node)
                definition = application.reflection.registry.require(
                    graph.graph_kind, graph.graph_version
                )
                if (
                    graph.graph_kind is ReflectionGraphKind.SEGMENT_REFLECT
                    and graph.graph_run_id in restart_targets
                    and definition.node(node.node_key).execution_kind
                    is ReflectionExecutionKind.AGGREGATE
                    and graph.graph_run_id not in restarted_graphs
                ):
                    with application.database.read() as connection:
                        snapshot = application.reflection_queue.runs.snapshot(
                            connection,
                            graph.community_id,
                            graph.character_id,
                            str(graph.graph_run_id),
                        )
                        successful = tuple(
                            (item.task_id, item.artifact_id)
                            for item in application.reflection_queue.nodes.for_graph(
                                connection, str(graph.graph_run_id)
                            )
                            if item.status == "completed"
                        )
                    assert await application.reflection_queue.apply_recovery(
                        lease,
                        datetime.now(UTC),
                        decision(
                            "execution_cancelled", FailureCategory.HARNESS, RecoveryAction.FAIL
                        ),
                    )
                    resumed = application.reflection.start_segment(
                        "community", graph.character_id, snapshot.source_id
                    )
                    assert resumed.status == "pending"
                    with pytest.raises(LeaseLostError):
                        application.reflection_graph_commit.commit(lease, datetime.now(UTC))
                    with application.database.read() as connection:
                        assert (
                            application.reflection_queue.runs.snapshot(
                                connection,
                                graph.community_id,
                                graph.character_id,
                                str(graph.graph_run_id),
                            )
                            == snapshot
                        )
                        assert (
                            tuple(
                                (item.task_id, item.artifact_id)
                                for item in application.reflection_queue.nodes.for_graph(
                                    connection, str(graph.graph_run_id)
                                )
                                if item.status == "completed"
                            )
                            == successful
                        )
                    restarted_graphs.add(graph.graph_run_id)
                    return
                worker = application.supervisor.workers["reflection-0"]
                outcome = await worker.dispatcher.registry.resolve("reflection").execute(lease)
                assert outcome.disposition is Disposition.COMPLETED, outcome
                if (
                    definition.node(node.node_key).execution_kind
                    is ReflectionExecutionKind.AGGREGATE
                ):
                    review = application.reflection_graph_commit.commit(lease, datetime.now(UTC))
                    assert review.status == "approved"
                    assert (
                        application.reflection_graph_commit.commit(lease, datetime.now(UTC))
                        == review
                    )
                    return

            for _ in range(3):
                pending = []
                while lease := await application.reflection_queue.claim(
                    "graph-finisher", datetime.now(UTC)
                ):
                    pending.append(lease)
                if not pending:
                    break
                await asyncio.gather(*(finish(lease) for lease in pending))
            with application.database.read() as connection:
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM reflection_graph_runs WHERE status = 'completed'"
                    ).fetchone()[0]
                    == 2
                )
                assert restarted_graphs == restart_targets
                segments = connection.execute(
                    "SELECT * FROM memory_segments ORDER BY character_id"
                ).fetchall()
                assert all(segment["status"] == "ingested" for segment in segments)
                assert all(segment["summary_version"] == "1" for segment in segments)
                assert all(segment["summary_text"] for segment in segments)
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM reflection_graph_results WHERE status = 'approved'"
                    ).fetchone()[0]
                    == 2
                )
                assert (
                    connection.execute("SELECT COUNT(*) FROM memory_source_coverage").fetchone()[0]
                    == 4
                )
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM reflection_node_tasks "
                        "WHERE status IN ('pending','processing','retry_wait')"
                    ).fetchone()[0]
                    == 0
                )
            batches = tuple(
                application.summary_batches.freeze(
                    "community",
                    character,
                    SummaryConsumer.CONTINUITY,
                )
                for character in ("first", "second")
            )
            assert all(batch is not None for batch in batches)
            assert batches[0].batch_id != batches[1].batch_id
            assert batches[0].sources != batches[1].sources
            for batch in batches:
                repeated = application.summary_batches.freeze(
                    "community",
                    batch.character_id,
                    SummaryConsumer.CONTINUITY,
                )
                assert repeated == batch
                for kind in (ReflectionGraphKind.CONTINUITY_COMPRESS,):
                    graph = application.reflection.start_summary(
                        "community", batch.character_id, batch.batch_id, kind
                    )
                    assert (
                        application.reflection.start_summary(
                            "community", batch.character_id, batch.batch_id, kind
                        )
                        == graph
                    )
                    with application.database.read() as connection:
                        snapshot = application.reflection_queue.runs.snapshot(
                            connection, "community", batch.character_id, str(graph.graph_run_id)
                        )
                        application.segment_context.sources.check_sources(connection, snapshot)
                        other = "香蕉918" if batch.character_id == "first" else "草莓417"
                        assert other not in snapshot.model_dump_json()
                        assert tuple(item.source_id for item in snapshot.materials) == tuple(
                            ref.segment_id for ref in batch.sources
                        )
            for _ in range(2):
                pending = []
                while lease := await application.reflection_queue.claim(
                    "continuity-finisher", datetime.now(UTC)
                ):
                    pending.append(lease)
                if not pending:
                    break
                await asyncio.gather(*(finish(lease) for lease in pending))
            with application.database.read() as connection:
                digests = connection.execute("SELECT * FROM conversation_digests").fetchall()
                assert len(digests) == 2
                assert all(digest["covers_through_sequence"] == 3 for digest in digests)
                assert all(digest["content_version"] == "1" for digest in digests)
            for batch in batches:
                assert (
                    application.summary_batches.freeze(
                        "community",
                        batch.character_id,
                        SummaryConsumer.CONTINUITY,
                    )
                    is None
                )
                application.reflection.start_summary(
                    "community",
                    batch.character_id,
                    batch.batch_id,
                    ReflectionGraphKind.MEMORY_ORGANIZE,
                )
            for _ in range(2):
                pending = []
                while lease := await application.reflection_queue.claim(
                    "organization-finisher", datetime.now(UTC)
                ):
                    pending.append(lease)
                if not pending:
                    break
                await asyncio.gather(*(finish(lease) for lease in pending))
            with application.database.read() as connection:
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM reflection_graph_runs WHERE status = 'completed'"
                    ).fetchone()[0]
                    == 6
                )
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM memory_organization_consumption"
                    ).fetchone()[0]
                    == 2
                )
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
                graphs = connection.execute(
                    "SELECT community_id,character_id,graph_run_id,graph_kind "
                    "FROM reflection_graph_runs"
                ).fetchall()
            for graph in graphs:
                view = jsonable_encoder(
                    application.reflection_view.get(
                        graph["community_id"], graph["character_id"], graph["graph_run_id"]
                    )
                )
                assert view["result"]["status"] == "approved"
                assert view["artifacts"] and view["traces"]
                kinds = {fact["fact_kind"] for fact in view["facts"]}
                if graph["graph_kind"] == "continuity_compress":
                    assert kinds == {"conversation_digest"}
                elif graph["graph_kind"] == "memory_organize":
                    assert "summary_consumption" in kinds
                    assert "conversation_digest" not in kinds
            for batch in batches:
                assert (
                    application.summary_batches.freeze(
                        "community",
                        batch.character_id,
                        SummaryConsumer.ORGANIZATION,
                    )
                    is None
                )
            application.intake.send(
                "community",
                "conversation",
                PlayerMessage(
                    "player",
                    "second-dinner",
                    "晚餐已经结束，我们确认下周六再次一起做饭。我负责买蔬菜，小槿负责米饭。"
                    "这个约定已经确定，请保留这项新安排。",
                ),
            )
            segment = application.memory_sealing.seal("community", "first")
            assert segment.first_sequence == 4
            application.reflection.start_segment("community", "first", segment.segment_id)
            for _ in range(3):
                pending = []
                while lease := await application.reflection_queue.claim(
                    "second-segment", datetime.now(UTC)
                ):
                    pending.append(lease)
                if not pending:
                    break
                await asyncio.gather(*(finish(lease) for lease in pending))
            batch = application.summary_batches.freeze(
                "community",
                "first",
                SummaryConsumer.CONTINUITY,
            )
            assert batch is not None
            assert batch.previous_digest_id
            assert batch.sources[0].segment_id == segment.segment_id
            graph = application.reflection.start_summary(
                "community", "first", batch.batch_id, ReflectionGraphKind.CONTINUITY_COMPRESS
            )
            with application.database.read() as connection:
                previous = connection.execute(
                    "SELECT * FROM conversation_digests WHERE digest_id=?",
                    (batch.previous_digest_id,),
                ).fetchone()
                snapshot = application.reflection_queue.runs.snapshot(
                    connection, "community", "first", str(graph.graph_run_id)
                )
                assert snapshot.materials[0].source_id == previous["digest_id"]
                assert snapshot.materials[0].content == previous["content"]
                assert snapshot.materials[0].covers_through_sequence == 3
                assert "香蕉918" not in snapshot.model_dump_json()
            for _ in range(2):
                pending = []
                while lease := await application.reflection_queue.claim(
                    "second-continuity", datetime.now(UTC)
                ):
                    pending.append(lease)
                if not pending:
                    break
                await asyncio.gather(*(finish(lease) for lease in pending))
            repeated = application.reflection.start_summary(
                "community", "first", batch.batch_id, ReflectionGraphKind.CONTINUITY_COMPRESS
            )
            assert repeated.graph_run_id == graph.graph_run_id
            assert repeated.status == "completed"
            assert (
                application.summary_batches.freeze(
                    "community",
                    "first",
                    SummaryConsumer.CONTINUITY,
                )
                is None
            )
            with application.database.read() as connection:
                digests = connection.execute(
                    "SELECT d.* FROM conversation_digests d "
                    "JOIN memory_summary_batches b ON b.batch_id=d.batch_id "
                    "WHERE b.character_id='first' ORDER BY covers_through_sequence"
                ).fetchall()
                assert [digest["covers_through_sequence"] for digest in digests] == [3, 4]
                assert digests[-1]["batch_id"] == batch.batch_id
                predecessor = connection.execute(
                    "SELECT previous_digest_id FROM memory_summary_batches WHERE batch_id=?",
                    (digests[-1]["batch_id"],),
                ).fetchone()
                assert predecessor[0] == previous["digest_id"]
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            clients = tuple(application.gateway._clients.values())
        assert all(client.is_closed() for client in clients)

    asyncio.run(run())
