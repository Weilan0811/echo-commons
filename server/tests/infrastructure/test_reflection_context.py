from concurrent.futures import ThreadPoolExecutor

import pytest
from historical_messages import historical_message
from test_memory_sealing import sealing
from test_message_perspective import build_system, send

from echo_commons.execution.records import ExecutionRecorder
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.services.context import CharacterContext
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.records import LongTermMemoryRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.reflection.contexts.graph import ReflectionContextPolicy
from echo_commons.modules.reflection.contexts.segment import SegmentContext
from echo_commons.modules.reflection.contexts.summaries import SummaryContext
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot, MessageMaterial
from echo_commons.modules.reflection.coordinator import ReflectionCoordinator
from echo_commons.modules.reflection.diagnostics import ReflectionRunView
from echo_commons.modules.reflection.registry import ReflectionGraphRegistry
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.diagnostics import ReflectionDiagnosticsRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.results import ResultRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.workflow import ReflectionWorkflow
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


def build_reflection(system):
    policy = ReflectionContextPolicy(frozenset({"memory_search"}), 32, 256, 20000)
    context = SegmentContext(
        policy,
        CharacterContext(
            system.catalog,
            InstanceRepository(),
            StateRepository(),
            RelationshipRepository(),
            system.world,
            CapabilityResolver(frozenset({"memory_search"})),
        ),
        CommunityRepository(),
        ConversationRepository(),
        system.world,
        LongTermMemoryRepository(),
        SegmentRepository(),
        ThoughtRepository(),
        system.retrieval,
    )
    coordinator = ReflectionCoordinator(
        system.database,
        ReflectionGraphRegistry(),
        SegmentRepository(),
        context,
        RunRepository(),
        NodeRepository(),
        SummaryContext(context.graph, MemoryProvenanceRepository(), context),
        ExecutionRecorder(system.database),
    )
    return context, coordinator


def test_stored_reflection_snapshot_has_exact_materials_and_private_identity(tmp_path):
    system = build_system(tmp_path)
    first = historical_message(
        system, "仅第一个角色知道草莓417", recipients=(ActorRef("character", "first"),)
    )
    second = historical_message(
        system, "仅第二个角色知道香蕉918", recipients=(ActorRef("character", "second"),)
    )
    public = send(system, "大家一起做饭", player="bob")
    context, coordinator = build_reflection(system)
    expected = {"first": (first, public), "second": (second, public)}
    for character in expected:
        segment = sealing(system).seal("community", character)
        run = coordinator.start_segment("community", character, segment.segment_id)
        assert coordinator.start_segment("community", character, segment.segment_id) == run
        with system.database.read() as connection:
            snapshot = RunRepository().snapshot(
                connection, "community", character, str(run.graph_run_id)
            )
            context.sources.check_sources(connection, snapshot)
            assert GraphContextSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
            messages = tuple(
                item for item in snapshot.materials if isinstance(item, MessageMaterial)
            )
            assert tuple(item.source_id for item in messages) == tuple(
                message.message_id for message in expected[character]
            )
            assert tuple(item.message.sender for item in messages) == (
                ActorRef("player", "alice"),
                ActorRef("player", "bob"),
            )
            other = "香蕉918" if character == "first" else "草莓417"
            assert other not in snapshot.model_dump_json()
            nodes = NodeRepository().for_graph(connection, str(run.graph_run_id))
            assert len(nodes) == 4
            root = next(node for node in nodes if node.node_key == "segment_summary_plan")
            node_input = prepare_node_input(
                snapshot,
                graph_run_id=str(run.graph_run_id),
                node_task_id=str(root.task_id),
                node_key=root.node_key,
                node_kind=root.node_kind,
            )
            assert node_input.read_policy.conversation_id is None
            assert node_input.read_policy.conversations == snapshot.conversations
            assert not hasattr(node_input.scope, "membership_id")
            assert {
                node.node_key for node in nodes if node.is_claimable(completed_node_keys=())
            } == {"segment_summary_plan"}
            with pytest.raises(NotFoundError):
                RunRepository().snapshot(connection, "community", "outside", str(run.graph_run_id))


def test_parallel_graph_creation_reuses_one_source_snapshot(tmp_path):
    system = build_system(tmp_path)
    send(system, "保留一次模型输入")
    segment = sealing(system).seal("community", "first")
    _, coordinator = build_reflection(system)
    with ThreadPoolExecutor(max_workers=2) as executor:
        runs = tuple(
            executor.map(
                lambda _: coordinator.start_segment("community", "first", segment.segment_id),
                range(2),
            )
        )
    assert runs[0] == runs[1]
    with system.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reflection_graph_runs").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM reflection_node_tasks").fetchone()[0] == 4
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_reflection_diagnostics_require_own_scope_and_preserve_source_versions(tmp_path):
    system = build_system(tmp_path)
    private = historical_message(
        system, "自己的私有材料", recipients=(ActorRef("character", "first"),)
    )
    historical_message(system, "另一角色的私有材料", recipients=(ActorRef("character", "second"),))
    segment = sealing(system).seal("community", "first")
    _, coordinator = build_reflection(system)
    run = coordinator.start_segment("community", "first", segment.segment_id)
    service = ReflectionRunView(
        system.database,
        RunRepository(),
        NodeRepository(),
        ArtifactRepository(),
        ResultRepository(),
        ReflectionDiagnosticsRepository(),
    )
    view = service.get("community", "first", str(run.graph_run_id))
    assert view["schema_version"] == 1
    assert view["snapshot"]["materials"][0]["source_id"] == private.message_id
    assert view["snapshot"]["materials"][0]["version"] == "1"
    assert "另一角色的私有材料" not in str(view)
    assert view["result"] is None
    assert view["facts"] == ()
    assert view["traces"][0]["kind"] == "reflection.graph.started"
    with pytest.raises(NotFoundError):
        service.get("community", "second", str(run.graph_run_id))


def test_explicit_reflection_workflow_reuses_segment_and_has_no_empty_summary_graph(tmp_path):
    system = build_system(tmp_path)
    send(system, "明确调度的真实消息")
    segment = sealing(system).seal("community", "first")
    _, coordinator = build_reflection(system)
    workflow = ReflectionWorkflow(
        coordinator,
        SummaryBatches(
            system.database,
            InstanceRepository(),
            ConversationRepository(),
            system.world,
            MemoryProvenanceRepository(),
            max_materials=256,
            max_chars=20000,
        ),
    )
    run = workflow.schedule_segment("community", "first", segment.segment_id)
    assert workflow.schedule_segment("community", "first", segment.segment_id) == run
    for consumer in SummaryConsumer:
        assert (
            workflow.schedule_summaries(
                "community",
                "first",
                consumer,
            )
            is None
        )
    with system.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM reflection_graph_runs").fetchone()[0] == 1
