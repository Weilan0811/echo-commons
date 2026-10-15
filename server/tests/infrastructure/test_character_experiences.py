from datetime import UTC, datetime, timedelta

import pytest
from support.memory import message_ids, sealing
from support.messages import build_system, send

from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.memory.services.retrieval import SearchScope
from echo_commons.shared.actors import ActorRef


def test_lifecycle_closes_experience_before_rejoined_messages(tmp_path):
    system = build_system(tmp_path)
    before = send(system, "退出前约好晚餐")
    service = sealing(system)
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    system.conversations.join("community", "conversation", ActorRef("character", "first"))
    after = send(system, "回来后接着聊天")
    with system.database.transaction() as connection:
        first = service.freeze(connection, "community", "first", automatic=True)
        assert message_ids(first) == (before.message_id,)
        assert service.freeze(connection, "community", "first", automatic=True) is None
    assert message_ids(service.seal("community", "first")) == (after.message_id,)


def test_delayed_scanner_preserves_historic_gap_and_new_message_extends_silence(tmp_path):
    from echo_commons.infrastructure.database.mapping import utc_text

    system = build_system(tmp_path)
    old = send(system, "昨天约定明天准备晚餐")
    new = send(system, "今天开始准备晚餐")
    now = datetime.now(UTC)
    with system.database.transaction() as connection:
        connection.execute(
            "UPDATE messages SET created_at_utc=? WHERE message_id=?",
            (utc_text(now - timedelta(seconds=1200)), old.message_id),
        )
    service = sealing(system)
    with system.database.transaction() as connection:
        segment = service.freeze(connection, "community", "first", observed_at=now, automatic=True)
        assert message_ids(segment) == (old.message_id,)
        assert (
            service.freeze(connection, "community", "first", observed_at=now, automatic=True)
            is None
        )
        assert message_ids(
            service.freeze(
                connection,
                "community",
                "first",
                observed_at=new.created_at_utc + timedelta(seconds=600),
                automatic=True,
            )
        ) == (new.message_id,)


def test_empty_summary_consumption_leaves_originals_for_long_term(tmp_path):
    from support.reflection import build_reflection

    from echo_commons.modules.memory.domain.summaries import SummaryConsumer
    from echo_commons.modules.memory.repositories.coverage import CoverageRepository
    from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
    from echo_commons.modules.memory.repositories.segments import SegmentRepository
    from echo_commons.modules.memory.services.ingestion import MemoryIngestion

    system = build_system(tmp_path)
    message = send(system, "周六晚餐请带上不含花生的甜点")
    service = sealing(system)
    segment = service.seal("community", "first")
    with system.database.transaction() as connection:
        MemoryIngestion(SegmentRepository(), CoverageRepository()).ingest(
            connection, "community", "first", segment.segment_id, None, datetime.now(UTC)
        )
    _, coordinator = build_reflection(system)
    from echo_commons.modules.characters.repositories.instances import InstanceRepository
    from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
    from echo_commons.modules.memory.services.batches import SummaryBatches

    batches = SummaryBatches(
        system.database,
        InstanceRepository(),
        ConversationRepository(),
        system.world,
        MemoryProvenanceRepository(),
        max_materials=256,
        max_chars=20000,
    )
    assert batches.freeze("community", "first", SummaryConsumer.CONTINUITY) is None
    batch = batches.freeze("community", "first", SummaryConsumer.ORGANIZATION)
    assert batch is not None
    with system.database.read() as connection:
        assert MemoryProvenanceRepository().continuity_consumed(connection, segment.segment_id)
        raw = connection.execute(
            "SELECT organization_sources_json FROM memory_summary_batches WHERE batch_id=?",
            (batch.batch_id,),
        ).fetchone()[0]
        assert message.message_id in raw
        assert not MemoryProvenanceRepository().organization_consumed(
            connection, segment.segment_id, ""
        )


def test_numbered_projection_rejects_read_only_evidence(tmp_path):
    from support.reflection import build_reflection

    from echo_commons.modules.reflection.contracts.candidates import StateModelAction
    from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind
    from echo_commons.modules.reflection.tasks.input import prepare_node_input
    from echo_commons.modules.reflection.tasks.projection import NodeReferences

    system = build_system(tmp_path)
    send(system, "此前的闲聊")
    send(system, "现在准备晚餐")
    service = sealing(system)
    service.max_messages = 1
    service.seal("community", "first")
    segment = service.seal("community", "first")
    _, coordinator = build_reflection(system)
    run = coordinator.start_segment("community", "first", segment.segment_id)
    with system.database.read() as connection:
        snapshot = coordinator.runs.snapshot(
            connection, "community", "first", str(run.graph_run_id)
        )
    node = prepare_node_input(
        snapshot,
        graph_run_id=str(run.graph_run_id),
        node_task_id="state",
        node_key="state_reflect",
        node_kind=ReflectionNodeKind.STATE_REFLECT,
    )
    refs = NodeReferences.from_input(node)
    previous = next(number for number, item in refs.originals.items() if item.context_only)
    with pytest.raises(ValueError, match="Only new materials"):
        refs.bind(
            StateModelAction(
                kind="state_reflection",
                state_kind="activity",
                value="我在准备晚餐。",
                sources=(previous,),
            )
        )


def direct_message(system, conversation, player, text):
    return system.intake.send("community", conversation, PlayerMessage(player, text, text))


def test_experience_boundaries_freeze_all_known_scenes_and_memberships(tmp_path):
    system = build_system(tmp_path)
    system.conversations.create(
        "community",
        "direct",
        (ActorRef("player", "alice"), ActorRef("character", "first")),
        conversation_id="first-private",
    )
    system.conversations.create(
        "community",
        "direct",
        (ActorRef("player", "bob"), ActorRef("character", "second")),
        conversation_id="other-private",
    )
    group = send(system, "群里商量晚餐")
    private = direct_message(system, "first-private", "alice", "私下商量饼干")
    hidden = direct_message(system, "other-private", "bob", "别人私下商量饼干")
    frozen_at = datetime.now(UTC)
    with system.database.read() as connection:
        bounds = system.world.freeze(
            connection, "community", ActorRef("character", "first"), frozen_at
        )
    later = direct_message(system, "first-private", "alice", "后来又商量饼干")
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    missing = send(system, "离开期间的消息")
    system.conversations.join("community", "conversation", ActorRef("character", "first"))
    joined = send(system, "重新加入后的消息")
    with system.database.read() as connection:
        actual = system.world.experiences(
            connection, "community", ActorRef("character", "first"), bounds, frozen_at
        )
        assert {item.message_id for item in actual} == {group.message_id, private.message_id}
        scope = SearchScope("community", "first", frozen_at, conversations=bounds)
        sources = system.retrieval.sources(connection, scope)
        assert ("message", private.message_id) in sources
        assert all(
            ("message", item.message_id) not in sources for item in (hidden, later, missing, joined)
        )


def test_character_segment_seals_cross_scene_sources_after_ten_minutes_of_silence(tmp_path):
    system = build_system(tmp_path)
    system.conversations.create(
        "community",
        "direct",
        (ActorRef("player", "alice"), ActorRef("character", "first")),
        conversation_id="private",
    )
    first = send(system, "群里约晚餐")
    last = direct_message(system, "private", "alice", "私下补充安排")
    service = sealing(system)
    with system.database.transaction() as connection:
        assert (
            service.freeze(
                connection,
                "community",
                "first",
                observed_at=last.created_at_utc + timedelta(seconds=599),
                automatic=True,
            )
            is None
        )
        segment = service.freeze(
            connection,
            "community",
            "first",
            observed_at=last.created_at_utc + timedelta(seconds=600),
            automatic=True,
        )
        assert message_ids(segment) == (first.message_id, last.message_id)
        assert {scene.conversation_id for scene in segment.conversations} == {
            "conversation",
            "private",
        }
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_budget_split_retains_read_only_context_without_resealing_it(tmp_path):
    system = build_system(tmp_path)
    first = send(system, "先商量晚餐")
    second = send(system, "然后补充安排")
    service = sealing(system)
    service.max_messages = 1
    left = service.seal("community", "first")
    right = service.seal("community", "first")
    assert message_ids(left) == (first.message_id,)
    assert message_ids(right) == (second.message_id,)
    assert tuple(source.source_id for source in right.context_sources) == (first.message_id,)
    assert service.seal("community", "first") is None
    with system.database.read() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM memory_segment_sources WHERE source_id=?", (first.message_id,)
            ).fetchone()[0]
            == 1
        )


def test_character_budget_reserves_a_complete_previous_message(tmp_path):
    system = build_system(tmp_path)
    originals = tuple(
        send(system, text * 10) for text in ("先准备晚餐", "接着准备菜", "最后再加汤")
    )
    service = sealing(system)
    service.max_material_chars = 120
    left = service.seal("community", "first")
    right = service.seal("community", "first")
    assert message_ids(left) == tuple(item.message_id for item in originals[:2])
    assert message_ids(right) == (originals[2].message_id,)
    assert right.context_sources


def test_version_nineteen_failed_and_processing_graphs_resume_current_protocol(tmp_path):
    import asyncio

    from support.application import settings_for
    from support.migrations import load_history

    from echo_commons.app.composition import assemble
    from echo_commons.execution.contracts import TaskLease
    from echo_commons.infrastructure.database.mapping import utc_datetime
    from echo_commons.infrastructure.database.migrations import initialize

    historical = load_history(19, tmp_path / "historical.sqlite3")
    with historical.read() as connection:
        failed_id = connection.execute(
            "SELECT node_task_id FROM reflection_node_tasks WHERE status='failed'"
        ).fetchone()[0]
        active = connection.execute(
            "SELECT * FROM reflection_node_tasks WHERE status='processing'"
        ).fetchone()
        run = connection.execute(
            "SELECT * FROM reflection_graph_runs WHERE graph_run_id=?", (active["graph_run_id"],)
        ).fetchone()
        processing = TaskLease(
            active["node_task_id"],
            "reflection",
            active["attempt_count"],
            active["lease_generation"],
            active["lease_owner"],
            utc_datetime(active["lease_until_utc"]),
            run["trace_id"],
            run["execution_generation"],
        )
    initialize(historical)
    app = assemble(
        settings_for(tmp_path, workers=False).model_copy(
            update={"database_path": str(historical.path)}
        )
    )
    queue = app.reflection_queue
    with historical.read() as connection:
        old = queue.nodes.get(connection, failed_id)
        failed_run = queue.run_for(connection, old)
        active = queue.nodes.get(connection, processing.task_id)
        assert old.status == "failed" and active.status == "pending"
        assert active.output_contract.version == "v6"
        assert active.lease_generation > processing.generation
        run = queue.run_for(connection, active)
        snapshot = queue.runs.snapshot(
            connection, run.community_id, run.character_id, str(run.graph_run_id)
        )
        assert snapshot.schema_version == 2 and snapshot.conversations
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert not asyncio.run(queue.renew(processing, datetime.now(UTC)))
    resumed = app.reflection.restart(
        failed_run.community_id, failed_run.character_id, str(old.graph_run_id)
    )
    assert resumed.status == "pending"
    assert asyncio.run(queue.claim("resumed-worker", datetime.now(UTC))) is not None
    assert app.gateway._clients == {}
