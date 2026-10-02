from datetime import UTC, datetime

from test_memory_sealing import sealing
from test_message_perspective import build_system, send

from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.organization import MemoryEntityDraft, MemoryEntryDraft
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.organization import MemoryOrganizationRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.memory.services.organization import MemoryOrganization


def test_unresolved_page_subject_is_saved_and_resolved_subject_is_linked(tmp_path):
    system = build_system(tmp_path)
    send(system, "我们约定周六一起做晚餐，带上草莓。")
    segment = sealing(system).seal("community", "first", "conversation")
    now = datetime.now(UTC)
    with system.database.transaction() as connection:
        MemoryIngestion(SegmentRepository(), CoverageRepository()).ingest(
            connection,
            "community",
            "first",
            segment.segment_id,
            "我记得对方约定周六一起做晚餐。",
            now,
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
    entries = tuple(
        MemoryEntryDraft(
            "event", "我记得周六一起做饭的约定。", "entity", subject, "recallable", 0.8, 0.7
        )
        for subject in ("晚餐约定", "dinner")
    )
    with system.database.transaction() as connection:
        service.organize(
            connection,
            "community",
            "first",
            batch.batch_id,
            entries,
            (MemoryEntityDraft("dinner", "event", "周六晚餐"),),
            (),
            False,
            now,
        )
    with system.database.read() as connection:
        saved = connection.execute(
            "SELECT subject_id,memory_id FROM memory_entries WHERE source_ref = ? ORDER BY rowid",
            (batch.batch_id,),
        ).fetchall()
        assert saved[0]["subject_id"] == "晚餐约定"
        assert saved[1]["subject_id"] != "dinner"
        links = connection.execute(
            "SELECT memory_id,entity_id FROM memory_entry_entities"
        ).fetchall()
        assert len(links) == 1
        assert tuple(links[0]) == (saved[1]["memory_id"], saved[1]["subject_id"])
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
