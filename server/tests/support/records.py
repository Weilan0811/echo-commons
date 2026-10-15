from datetime import UTC, datetime

from echo_commons.execution.clock import utc_now
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.organization import (
    FactAdd,
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
from support.http import create_group as create_base_group
from support.memory import sealing
from support.messages import send


def create_memory_group(client, *, memory_mode="full"):
    create_base_group(client, memory_mode=memory_mode)
    if memory_mode == "simple":
        return
    app = client.app.state.application
    texts = (
        "我们周六一起修理蓝风铃。",
        "周日一起去旧钟铺。",
        "下个月一起去青石镇。",
        "今晚一起做晚餐。",
    )
    receipts = [
        client.post(
            "/api/conversations/conversation/messages",
            json=dict(player_id="alice", client_message_id=f"source{i}", text=text),
        ).json()
        for i, text in enumerate(texts, 1)
    ]
    segment = app.memory_sealing.seal("community", "first")
    now = utc_now()
    with app.database.transaction() as connection:
        app.reflection_graph_commit.facts.memory.ingest(
            connection, "community", "first", segment.segment_id, "对方提出四个具体约定。", now
        )
    batch = app.reflection_workflow.batches.freeze(
        "community",
        "first",
        SummaryConsumer.ORGANIZATION,
    )
    sources = tuple(
        OrganizationEvidence(
            kind="message", source_id=item["message_id"], version="1", known_at_utc=now
        )
        for item in receipts
    )
    facts = tuple(
        FactAdd(
            local_key=f"fact{i}",
            fact=MemoryFactContent(topic="约定", content=text),
            evidence_refs=(f"message:{source.source_id}",),
        )
        for i, (text, source) in enumerate(zip(texts, sources, strict=True), 1)
    )
    with app.database.transaction() as connection:
        app.reflection_graph_commit.facts.organization.organize(
            connection, "community", "first", batch.batch_id, facts, (), sources, True, now, now
        )


def prepare_records(system):
    now = datetime.now(UTC)
    facts, sources = [], []
    for index, text in enumerate(("我们约定周六一起做晚餐。", "我喜欢吃草莓。"), 1):
        receipt = send(
            system,
            text,
            client=f"material-{index}",
            reply=sources[-1].source_id if sources else None,
        )
        segment = sealing(system).seal("community", "first")
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
        SummaryConsumer.ORGANIZATION,
    )
    service = MemoryOrganization(provenance, MemoryOrganizationRepository(), system.intake.indexer)
    return service, provenance, batch, tuple(facts), tuple(sources), now
