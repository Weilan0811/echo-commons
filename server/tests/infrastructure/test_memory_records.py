import json
from datetime import UTC, datetime

import pytest
from test_memory_sealing import sealing
from test_message_perspective import build_system, send
from test_reflection_context import build_reflection

from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.organization import (
    CognitionAdd,
    FactAdd,
    FactCandidateRef,
    MemoryCognitionContent,
    MemoryFactContent,
    OrganizationEvidence,
)
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.organization import MemoryOrganizationRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.memory.services.organization import MemoryOrganization
from echo_commons.modules.reflection.contracts.candidates import (
    MemoryCognitionReflectAction,
    MemoryFactExtractAction,
    MemoryFactReviewAction,
    MemoryModelAction,
)
from echo_commons.modules.reflection.contracts.context import ArtifactInput
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind, ReflectionNodeKind
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.projection import NodeReferences
from echo_commons.shared.errors import ConflictError, NotFoundError


def prepare(system):
    now = datetime.now(UTC)
    facts, sources = [], []
    for index, text in enumerate(("我们约定周六一起做晚餐。", "我喜欢吃草莓。"), 1):
        receipt = send(
            system,
            text,
            client=f"material-{index}",
            reply=sources[-1].source_id if sources else None,
        )
        segment = sealing(system).seal("community", "first", "conversation")
        with system.database.transaction() as connection:
            MemoryIngestion(SegmentRepository(), CoverageRepository()).ingest(
                connection, "community", "first", segment.segment_id, text, now
            )
        source = OrganizationEvidence(
            kind="message", source_id=receipt.message_id, version="1", known_at_utc=now
        )
        sources.append(source)
        facts.append(
            FactAdd(
                local_key=f"fact{index}",
                evidence_refs=(f"message:{receipt.message_id}",),
                fact=MemoryFactContent(
                    topic="约定" if index == 1 else "喜好",
                    content=text,
                ),
            )
        )
    provenance = MemoryProvenanceRepository()
    batch = SummaryBatches(
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
        "conversation",
        SummaryConsumer.ORGANIZATION,
        through_sequence=segment.last_sequence,
    )
    service = MemoryOrganization(provenance, MemoryOrganizationRepository(), system.intake.indexer)
    return service, provenance, batch, tuple(facts), tuple(sources), now


def test_facts_have_individual_original_support_and_owned_scope(tmp_path):
    system = build_system(tmp_path)
    service, provenance, batch, facts, sources, now = prepare(system)
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
    service, provenance, batch, facts, sources, now = prepare(system)
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
    service, _, batch, facts, sources, now = prepare(system)
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
    service, _, batch, _, sources, now = prepare(system)
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
    _, _, batch, _, _, now = prepare(system)
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
    assert len(bound.facts) == 1
    assert bound.facts[0].local_key == "fact1"
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
    _, _, batch, _, _, now = prepare(system)
    labels = NodeReferences.from_input(organization_input(system, batch, now))
    assert all(material.kind != "segment_summary" for material in labels.originals.values())


def test_cognition_can_use_reviewed_fact_numbers_without_raw_thought(tmp_path):
    system = build_system(tmp_path)
    _, _, batch, facts, _, now = prepare(system)
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
    service, _, batch, facts, sources, now = prepare(system)
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
