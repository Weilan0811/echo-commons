import asyncio
import json
from datetime import UTC, datetime

import pytest
from support.application import settings_for
from support.memory import sealing
from support.messages import build_system, send
from support.records import prepare_records
from support.reflection import build_reflection

from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.execution.clock import utc_now
from echo_commons.execution.recovery import decision
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.organization import (
    CognitionAdd,
    FactCandidateRef,
    MemoryCognitionContent,
    MemoryFactContent,
    OrganizationEvidence,
)
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.reflection.contracts.candidates import (
    FactReviewModelAction,
    MemoryCognitionReflectAction,
    MemoryFactExtractAction,
    MemoryFactReviewAction,
    MemoryModelAction,
)
from echo_commons.modules.reflection.contracts.context import ArtifactInput
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind, ReflectionNodeKind
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.projection import NodeReferences
from echo_commons.modules.reflection.tasks.review import bind_fact_review, check_memory_action
from echo_commons.shared.errors import ConflictError, NotFoundError


@pytest.mark.model
def test_real_fact_review_without_old_records_avoids_review_call(tmp_path):
    system = build_system(tmp_path)
    _, _, batch, _, _, _ = prepare_records(system)

    async def run():
        settings = settings_for(tmp_path, workers=False).model_copy(
            update={"database_path": str(system.database.path)}
        )
        async with application_lifecycle(settings) as app:
            graph = app.reflection.start_summary(
                "community", "first", batch.batch_id, ReflectionGraphKind.MEMORY_ORGANIZE
            )
            dispatcher = app.supervisor.workers["tasks-0"].dispatcher
            for _ in range(6):
                lease = await app.reflection_queue.claim(dispatcher.owner, utc_now())
                assert lease is not None, "Unexpected retry; inspect the failure before rerunning"
                await dispatcher._execute(lease)
                with app.database.read() as connection:
                    current = app.reflection.runs.get(
                        connection, "community", "first", str(graph.graph_run_id)
                    )
                if current.is_terminal:
                    break
            assert current.status == "completed"
            with app.database.read() as connection:
                node = next(
                    node
                    for node in app.reflection.nodes.for_graph(connection, str(graph.graph_run_id))
                    if node.node_key == "fact_review"
                )
                artifact = app.reflection_queue.artifacts.get(
                    connection, str(graph.graph_run_id), str(node.artifact_id)
                )
                assert artifact.invocation_id is None
                assert connection.execute("SELECT count(*) FROM memory_facts").fetchone()[0] > 0
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    asyncio.run(run())


@pytest.mark.model
def test_real_fact_review_updates_and_recovers_only_cognition(tmp_path):
    system = build_system(tmp_path)
    service, provenance, batch, facts, sources, now = prepare_records(system)
    # 保存一份正文提取错误的旧记录，作为真实整理流程的输入。
    facts = (
        facts[0].model_copy(
            update={
                "fact": MemoryFactContent(topic="晚餐约定", content="alice说周六大家一起做晚餐。")
            }
        ),
        facts[1].model_copy(
            update={"fact": MemoryFactContent(topic="偏好", content="alice说自己喜欢香蕉。")}
        ),
    )
    with system.database.transaction() as connection:
        service.organize(
            connection, "community", "first", batch.batch_id, facts, (), sources, True, now, now
        )
    send(
        system,
        "再次确认：周六我们一起做晚餐，这个约定没变。"
        "之前把我的偏好写成喜欢香蕉的记录提取错了，我说的一直是喜欢草莓。"
        "另外请记住，我家门牌是锦绣路18号。",
        client="real-review",
    )
    segment = sealing(system).seal("community", "first")
    now = datetime.now(UTC)
    with system.database.transaction() as connection:
        MemoryIngestion(SegmentRepository(), CoverageRepository()).ingest(
            connection,
            "community",
            "first",
            segment.segment_id,
            "确认约定、纠正提取并告知地址。",
            now,
        )
    next_batch = SummaryBatches(
        system.database,
        InstanceRepository(),
        ConversationRepository(),
        system.world,
        provenance,
        max_materials=256,
        max_chars=20000,
    ).freeze(
        "community",
        "first",
        SummaryConsumer.ORGANIZATION,
    )

    async def run():
        settings = settings_for(tmp_path, workers=False).model_copy(
            update={
                "database_path": str(system.database.path),
                "debug_capture_enabled": True,
                "debug_capture_path": str(tmp_path / "capture"),
            }
        )
        async with application_lifecycle(settings) as app:
            graph = app.reflection.start_summary(
                "community", "first", next_batch.batch_id, ReflectionGraphKind.MEMORY_ORGANIZE
            )
            dispatcher = app.supervisor.workers["tasks-0"].dispatcher
            cancelled = False
            for _ in range(12):
                lease = await app.reflection_queue.claim(dispatcher.owner, utc_now())
                assert lease is not None, "Unexpected model retry; inspect capture before rerunning"
                with app.database.read() as connection:
                    node = app.reflection.nodes.get(connection, lease.task_id)
                if node.node_key == "cognition_reflect" and not cancelled:
                    cancelled = True
                    await app.reflection_queue.apply_recovery(
                        lease,
                        utc_now(),
                        decision(
                            "execution_cancelled", FailureCategory.HARNESS, RecoveryAction.FAIL
                        ),
                    )
                else:
                    await dispatcher._execute(lease)
                with app.database.read() as connection:
                    current = app.reflection.runs.get(
                        connection, "community", "first", str(graph.graph_run_id)
                    )
                if current.is_terminal:
                    break
            assert current.status == "partial"
            with app.database.read() as connection:
                nodes = app.reflection.nodes.for_graph(connection, str(graph.graph_run_id))
                reviewed = next(node for node in nodes if node.node_key == "fact_review")
                payload = app.reflection_queue.artifacts.get(
                    connection, str(graph.graph_run_id), str(reviewed.artifact_id)
                ).payload.to_dict()
                operations = [item["operation"] for item in payload["facts"]]
                assert {"add", "support", "correct"} <= set(operations), payload
                before = connection.execute("SELECT count(*) FROM memory_facts").fetchone()[0]
            resumed = app.reflection.restart("community", "first", str(graph.graph_run_id))
            for _ in range(6):
                lease = await app.reflection_queue.claim(dispatcher.owner, utc_now())
                assert lease is not None, "Unexpected model retry; inspect capture before rerunning"
                with app.database.read() as connection:
                    assert app.reflection.nodes.get(connection, lease.task_id).node_key not in (
                        "fact_extract",
                        "fact_review",
                    )
                await dispatcher._execute(lease)
                with app.database.read() as connection:
                    current = app.reflection.runs.get(
                        connection, "community", "first", str(resumed.graph_run_id)
                    )
                if current.is_terminal:
                    break
            assert current.status == "completed"
            with app.database.read() as connection:
                assert (
                    connection.execute("SELECT count(*) FROM memory_facts").fetchone()[0] == before
                )
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            print("Real fact review operations:", operations, "; cognition recovery completed")

    asyncio.run(run())


def test_fact_learned_at_uses_latest_actual_message_time(tmp_path):
    system = build_system(tmp_path)
    service, _, batch, facts, sources, _ = prepare_records(system)
    with system.database.read() as connection:
        times = [
            datetime.fromisoformat(
                connection.execute(
                    "SELECT created_at_utc FROM messages WHERE message_id=?", (source.source_id,)
                ).fetchone()[0]
            )
            for source in sources
        ]
    sources = tuple(
        source.model_copy(update={"known_at_utc": time})
        for source, time in zip(sources, times, strict=True)
    )
    combined = facts[0].model_copy(
        update={"evidence_refs": tuple(f"message:{source.source_id}" for source in sources)}
    )
    now = datetime.now(UTC)
    with system.database.transaction() as connection:
        service.organize(
            connection,
            "community",
            "first",
            batch.batch_id,
            (combined,),
            (),
            sources,
            True,
            now,
            now,
        )
        saved = connection.execute("SELECT learned_at_utc FROM memory_facts").fetchone()[0]
        assert datetime.fromisoformat(saved) == max(times)


def test_review_binds_semantic_updates_without_reconsuming_old_originals(tmp_path):
    system = build_system(tmp_path)
    service, provenance, batch, facts, sources, now = prepare_records(system)
    cognition = CognitionAdd(
        cognition=MemoryCognitionContent(
            topic="饮食认识", content="我以为对方喜欢草莓。", applies_to="饮食认识"
        ),
        supporting_facts=(FactCandidateRef(local_key="fact2"),),
    )
    with system.database.transaction() as connection:
        service.organize(
            connection,
            "community",
            "first",
            batch.batch_id,
            facts,
            (cognition,),
            sources,
            True,
            now,
            now,
        )
    send(
        system,
        "晚餐还是周六一起做。之前记录把我的香蕉偏好写成了草莓，请更正。",
        client="review-new-evidence",
    )
    segment = sealing(system).seal("community", "first")
    now = datetime.now(UTC)
    with system.database.transaction() as connection:
        MemoryIngestion(SegmentRepository(), CoverageRepository()).ingest(
            connection,
            "community",
            "first",
            segment.segment_id,
            "确认晚餐并指出偏好记录错误。",
            now,
        )
    next_batch = SummaryBatches(
        system.database,
        InstanceRepository(),
        ConversationRepository(),
        system.world,
        provenance,
        max_materials=256,
        max_chars=20000,
    ).freeze(
        "community",
        "first",
        SummaryConsumer.ORGANIZATION,
    )
    extraction = organization_input(system, next_batch, now)
    labels = NodeReferences.from_input(extraction)
    message_number = next(n for n, value in labels.originals.items() if value.kind == "message")
    assert {
        value.source_id for value in labels.originals.values() if value.kind == "message"
    }.isdisjoint(source.source_id for source in sources)
    proposed = labels.bind(
        MemoryModelAction.model_validate(
            {
                "items": [
                    {"content": "alice和大家约好周六一起做晚餐。", "sources": [message_number]},
                    {
                        "content": "alice指出偏好记录写错，喜欢的是香蕉。",
                        "sources": [message_number],
                    },
                ]
            }
        )
    )
    assert all(item.operation == "add" for item in proposed.facts)
    artifact = ArtifactInput(
        artifact_id="candidate-artifact",
        node_key="fact_extract",
        content_version="1",
        payload=proposed,
    )
    review = prepare_node_input(
        extraction.graph_snapshot,
        graph_run_id="review-run",
        node_task_id="review-node",
        node_key="fact_review",
        node_kind=ReflectionNodeKind.FACT_REVIEW,
        artifacts=(artifact,),
    )
    targets = NodeReferences.from_input(review)
    by_content = {targets.bodies[n]["content"]: n for n in targets.records}
    decisions = FactReviewModelAction.model_validate(
        {
            "items": [
                {"item": 1, "action": "support", "target": by_content[facts[0].fact.content]},
                {"item": 2, "action": "correct", "target": by_content[facts[1].fact.content]},
            ]
        }
    )
    approved = bind_fact_review(review, decisions)
    assert [item.operation for item in approved.facts] == ["support", "correct"]
    assert (
        check_memory_action(
            review,
            approved,
        )
        is None
    )
    with system.database.transaction() as connection:
        service.organize(
            connection,
            "community",
            "first",
            next_batch.batch_id,
            approved.facts,
            (),
            (
                OrganizationEvidence(
                    kind="message",
                    source_id=segment.sources[0].source_id,
                    version="1",
                    known_at_utc=now,
                ),
            ),
            True,
            now,
            now,
        )
        assert connection.execute("SELECT count(*) FROM memory_facts").fetchone()[0] == 4
        assert (
            connection.execute(
                "SELECT count(*) FROM memory_facts WHERE status='invalid'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute("SELECT status FROM memory_cognitions").fetchone()[0]
            == "needs_review"
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(ValueError):
        bind_fact_review(review, FactReviewModelAction.model_validate({"items": []}))
    with pytest.raises(ValueError):
        bind_fact_review(
            review,
            FactReviewModelAction.model_validate(
                {
                    "items": [
                        {
                            "item": 1,
                            "action": "support",
                            "target": by_content[facts[0].fact.content],
                        },
                        {
                            "item": 2,
                            "action": "correct",
                            "target": by_content[facts[0].fact.content],
                        },
                    ]
                }
            ),
        )


def test_facts_have_individual_original_support_and_owned_scope(tmp_path):
    system = build_system(tmp_path)
    service, provenance, batch, facts, sources, now = prepare_records(system)
    with system.database.transaction() as connection:
        service.organize(
            connection, "community", "first", batch.batch_id, facts, (), sources, True, now, now
        )
    with system.database.read() as connection:
        rows = connection.execute("SELECT * FROM memory_facts ORDER BY rowid").fetchall()
        assert len(rows) == 2
        for row, operation in zip(rows, facts, strict=True):
            evidence = provenance.record_sources(
                connection, "community", "first", "fact", row["memory_id"], 1
            )
            assert len(evidence) == 1 and evidence[0]["readable"]
            assert evidence[0]["content"].endswith(operation.fact.content)
            with pytest.raises(NotFoundError):
                provenance.record_sources(
                    connection, "community", "second", "fact", row["memory_id"], 1
                )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_partial_fact_phase_is_saved_once_and_cognition_covers_sources_later(tmp_path):
    system = build_system(tmp_path)
    service, provenance, batch, facts, sources, now = prepare_records(system)
    with system.database.transaction() as connection:
        service.organize(
            connection, "community", "first", batch.batch_id, facts, (), sources, False, now, now
        )
        assert connection.execute("SELECT count(*) FROM memory_facts").fetchone()[0] == 2
        assert (
            connection.execute("SELECT count(*) FROM memory_organization_consumption").fetchone()[0]
            == 0
        )
        cognition = CognitionAdd(
            cognition=MemoryCognitionContent(
                topic="周末的约定",
                content="周六有人一起做晚餐，这件事让我挺期待的。",
                applies_to="周六一起做晚餐",
            ),
            supporting_facts=(FactCandidateRef(local_key="fact1"),),
        )
        service.organize(
            connection,
            "community",
            "first",
            batch.batch_id,
            (),
            (cognition,),
            sources,
            True,
            now,
            now,
        )
        assert connection.execute("SELECT count(*) FROM memory_facts").fetchone()[0] == 2
        row = connection.execute("SELECT * FROM memory_cognitions").fetchone()
        evidence = provenance.record_sources(
            connection, "community", "first", "cognition", row["memory_id"], 1
        )
        assert evidence and all(item["readable"] for item in evidence)
        assert (
            connection.execute("SELECT count(*) FROM memory_organization_consumption").fetchone()[0]
            == 2
        )
        phases = connection.execute(
            "SELECT stage FROM memory_organization_stages ORDER BY stage"
        ).fetchall()
        assert [row[0] for row in phases] == ["cognitions", "facts"]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_summary_is_not_original_fact_support(tmp_path):
    system = build_system(tmp_path)
    service, _, batch, facts, sources, now = prepare_records(system)
    bad = facts[0].model_copy(
        update={"evidence_refs": (f"segment_summary:{batch.sources[0].segment_id}",)}
    )
    with pytest.raises(ConflictError), system.database.transaction() as connection:
        service.organize(
            connection, "community", "first", batch.batch_id, (bad,), (), sources, True, now, now
        )
    with system.database.read() as connection:
        assert connection.execute("SELECT count(*) FROM memory_facts").fetchone()[0] == 0
        assert (
            connection.execute("SELECT count(*) FROM memory_organization_stages").fetchone()[0] == 0
        )


def test_explicit_no_op_covers_originals_without_records(tmp_path):
    system = build_system(tmp_path)
    service, _, batch, _, sources, now = prepare_records(system)
    with system.database.transaction() as connection:
        service.organize(
            connection, "community", "first", batch.batch_id, (), (), sources, True, now, now
        )
        assert connection.execute("SELECT count(*) FROM memory_facts").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT count(*) FROM memory_organization_consumption WHERE outcome='no_op'"
            ).fetchone()[0]
            == 2
        )
        stage = connection.execute(
            "SELECT references_json FROM memory_organization_stages WHERE stage='facts'"
        ).fetchone()
        assert json.loads(stage[0]) == {}


def organization_input(system, batch, now, *, cognition=False, artifacts=()):
    _, coordinator = build_reflection(system)
    with system.database.read() as connection:
        snapshot = coordinator.summaries.prepare(
            connection,
            "community",
            "first",
            batch.batch_id,
            ReflectionGraphKind.MEMORY_ORGANIZE,
            now,
        )
    return prepare_node_input(
        snapshot,
        graph_run_id="contract-run",
        node_task_id="contract-node",
        node_key="cognition_reflect" if cognition else "fact_extract",
        node_kind=ReflectionNodeKind.COGNITION_REFLECT
        if cognition
        else ReflectionNodeKind.FACT_EXTRACT,
        artifacts=artifacts,
    )


def test_numbered_model_items_bind_original_evidence_and_program_keys(tmp_path):
    from echo_commons.modules.reflection.tasks.prompt import render_material

    system = build_system(tmp_path)
    _, _, batch, _, _, now = prepare_records(system)
    labels = NodeReferences.from_input(organization_input(system, batch, now))
    messages = [(n, value) for n, value in labels.originals.items() if value.kind == "message"]
    assert [value.message.sequence for _, value in messages] == sorted(
        value.message.sequence for _, value in messages
    )
    assert f"回复材料{messages[0][0]}（alice）" in render_material(messages[1][1], labels)
    number = next(n for n, material in labels.originals.items() if material.kind == "message")
    action = MemoryModelAction.model_validate(
        {
            "items": [
                {
                    "content": "说话者说自己喜欢吃草莓。",
                    "sources": [number, number],
                },
                {"content": "说话者说自己喜欢吃草莓。", "sources": [number]},
            ]
        }
    )
    bound = labels.bind(action)
    assert isinstance(bound, MemoryFactExtractAction)
    assert len(bound.facts) == 2
    assert bound.facts[0].local_key == "fact1"
    assert bound.facts[1].local_key == "fact2"
    assert bound.facts[0].fact.occurred_at_utc is None
    assert bound.facts[0].evidence_refs == (labels.sources[number],)
    assert bound.facts[0].fact.participants == (labels.originals[number].message.sender,)
    assert labels.display_record(
        {
            "evidence": [
                {
                    "source_kind": "memory_segment",
                    "content_status": "unavailable",
                    "content": "",
                    "source_ref": "internal-source",
                }
            ],
            "target_name": "小明",
            "target_id": "internal-target",
        }
    ) == {
        "evidence": [
            {"source_kind": "memory_segment", "content_status": "unavailable", "content": ""}
        ],
        "target_name": "小明",
    }
    with pytest.raises(ValueError, match="Unknown material"):
        labels.bind(
            MemoryModelAction.model_validate(
                {
                    "items": [
                        {"content": "正文", "sources": [9999]},
                    ]
                }
            )
        )


def test_summary_is_not_a_numbered_fact_source(tmp_path):
    system = build_system(tmp_path)
    _, _, batch, _, _, now = prepare_records(system)
    labels = NodeReferences.from_input(organization_input(system, batch, now))
    assert all(material.kind != "segment_summary" for material in labels.originals.values())


def test_cognition_can_use_reviewed_fact_numbers_without_raw_thought(tmp_path):
    system = build_system(tmp_path)
    _, _, batch, facts, _, now = prepare_records(system)
    artifact = ArtifactInput(
        artifact_id="reviewed-facts",
        node_key="fact_review",
        content_version="1",
        payload=MemoryFactReviewAction(
            facts=facts, evidence_refs=tuple(ref for fact in facts for ref in fact.evidence_refs)
        ),
    )
    node = organization_input(system, batch, now, cognition=True, artifacts=(artifact,))
    labels = NodeReferences.from_input(node)
    number = next(iter(labels.candidates))
    action = MemoryModelAction.model_validate(
        {
            "items": [
                {"content": "周六的晚餐可以一起准备。", "sources": [number]},
            ]
        }
    )
    bound = labels.bind(action)
    assert isinstance(bound, MemoryCognitionReflectAction)
    assert bound.cognitions[0].supporting_facts == (FactCandidateRef(local_key="fact1"),)
    assert bound.cognitions[0].evidence_refs == ()
    assert labels.bind(MemoryModelAction(items=())).kind == "no_op"


def test_old_cognition_alone_does_not_cancel_supported_items(tmp_path):
    from echo_commons.modules.reflection.tasks.prompt import render_material

    system = build_system(tmp_path)
    service, _, batch, facts, sources, now = prepare_records(system)
    old = CognitionAdd(
        cognition=MemoryCognitionContent(
            topic="周六晚餐", content="我期待周六一起准备晚餐。", applies_to="周六晚餐"
        ),
        supporting_facts=(FactCandidateRef(local_key="fact1"),),
    )
    with system.database.transaction() as connection:
        service.organize(
            connection, "community", "first", batch.batch_id, facts, (old,), sources, True, now, now
        )
    node = organization_input(system, batch, datetime.now(UTC), cognition=True)
    labels = NodeReferences.from_input(node)
    previous = next(
        n for n, reference in labels.records.items() if reference.record_kind == "cognition"
    )
    fact = next(n for n, reference in labels.records.items() if reference.record_kind == "fact")
    assert "角色认识" in render_material(labels.originals[previous], labels)
    assert "事实记录" in render_material(labels.originals[fact], labels)
    fact_labels = NodeReferences.from_input(organization_input(system, batch, datetime.now(UTC)))
    old_fact = next(iter(fact_labels.records))
    assert (
        fact_labels.bind(
            MemoryModelAction.model_validate(
                {"items": [{"content": "旧信息改写", "sources": [old_fact]}]}
            )
        ).kind
        == "no_op"
    )
    unsupported = {"content": "我现在更期待那顿晚餐了。", "sources": [previous]}
    assert labels.bind(MemoryModelAction.model_validate({"items": [unsupported]})).kind == "no_op"
    bound = labels.bind(
        MemoryModelAction.model_validate(
            {
                "items": [
                    unsupported,
                    {
                        "content": "既然约好周六一起做饭，我可以提前把食材准备好。",
                        "sources": [fact],
                    },
                ]
            }
        )
    )
    assert len(bound.cognitions) == 1
    assert bound.cognitions[0].supporting_facts
    related = labels.bind(
        MemoryModelAction.model_validate(
            {
                "items": [
                    {"content": "我可以提前准备食材。", "sources": [previous, fact]},
                    {"content": "我想问清楚他周六什么时候到。", "sources": [previous, fact]},
                ]
            }
        )
    )
    assert len(related.cognitions) == 2
    assert all(item.operation == "add" for item in related.cognitions)
