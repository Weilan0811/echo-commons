import json
from datetime import UTC, datetime

import pytest
from test_memory_sealing import sealing
from test_message_perspective import build_system, send

from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.organization import MemoryEntryDraft, OrganizationEvidence
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.organization import MemoryOrganizationRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.memory.services.organization import MemoryOrganization
from echo_commons.modules.memory.services.view_materials import ViewMaterialPreparation
from echo_commons.shared.errors import ConflictError, NotFoundError


def prepare(system):
    now = datetime.now(UTC)
    summaries = []
    for index, text in enumerate(("我们约定周六一起做晚餐。", "我喜欢吃草莓。")):
        send(system, text, client=f"material-{index}")
        segment = sealing(system).seal("community", "first", "conversation")
        with system.database.transaction() as connection:
            MemoryIngestion(SegmentRepository(), CoverageRepository()).ingest(
                connection, "community", "first", segment.segment_id, text, now
            )
        summaries.append(segment.segment_id)
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
    with system.database.read() as connection:
        rows = provenance.batch_summaries(connection, batch)
        entries = tuple(
            MemoryEntryDraft(
                "fact",
                row["summary_text"],
                "recallable",
                1,
                0.7,
                (
                    OrganizationEvidence(
                        "segment_summary", row["segment_id"], row["summary_version"]
                    ),
                ),
            )
            for row in rows
        )
    return service, provenance, batch, entries, now


def test_pages_preserve_individual_evidence_and_role_scope(tmp_path):
    system = build_system(tmp_path)
    service, provenance, batch, entries, now = prepare(system)
    with system.database.transaction() as connection:
        service.organize(connection, "community", "first", batch.batch_id, entries, False, now)
    with system.database.read() as connection:
        pages = connection.execute(
            "SELECT * FROM memory_entries WHERE source_ref=? ORDER BY rowid", (batch.batch_id,)
        ).fetchall()
        assert len(pages) == 2
        for page, draft in zip(pages, entries, strict=True):
            sources = provenance.entry_sources(connection, "community", "first", page["memory_id"])
            assert len(sources) == 1
            assert sources[0]["source_id"] == draft.sources[0].source_id
            assert sources[0]["content"] == draft.content and sources[0]["readable"]
            with pytest.raises(NotFoundError):
                provenance.entry_sources(connection, "community", "second", page["memory_id"])
        materials = ViewMaterialPreparation().select(
            connection,
            "community",
            "first",
            datetime.now(UTC),
            {page["memory_id"] for page in pages},
            max_count=32,
            max_chars=20000,
            batch_id="reading",
            version="1",
        )
        selected = {
            item["source_id"]: json.loads(item["content"])
            for item in materials
            if item["fact_kind"] == "memory_entry"
        }
        for page, draft in zip(pages, entries, strict=True):
            assert selected[page["memory_id"]]["support_in_memory_id"] is None
            evidence = selected[page["memory_id"]]["supporting_materials"]
            assert [item["content"] for item in evidence] == [draft.content]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    with (
        pytest.raises(ConflictError, match="already been consumed"),
        system.database.transaction() as connection,
    ):
        service.organize(connection, "community", "first", batch.batch_id, entries, False, now)


@pytest.mark.parametrize("source", [None, OrganizationEvidence("segment_summary", "unknown", "1")])
def test_missing_or_foreign_page_evidence_does_not_consume_batch(tmp_path, source):
    system = build_system(tmp_path)
    service, _, batch, entries, now = prepare(system)
    page = MemoryEntryDraft(
        "fact", entries[0].content, "recallable", 1, 0.7, () if source is None else (source,)
    )
    with pytest.raises(ConflictError), system.database.transaction() as connection:
        service.organize(connection, "community", "first", batch.batch_id, (page,), False, now)
    with system.database.read() as connection:
        assert (
            connection.execute(
                "SELECT * FROM memory_entries WHERE source_ref=?", (batch.batch_id,)
            ).fetchall()
            == []
        )
        assert (
            connection.execute(
                "SELECT * FROM memory_organization_consumption WHERE batch_id=?", (batch.batch_id,)
            ).fetchall()
            == []
        )


def test_explicit_no_op_consumes_material_without_pages(tmp_path):
    system = build_system(tmp_path)
    service, _, batch, _, now = prepare(system)
    with system.database.transaction() as connection:
        service.organize(connection, "community", "first", batch.batch_id, (), True, now)
        assert (
            connection.execute(
                "SELECT count(*) FROM memory_organization_consumption "
                "WHERE batch_id=? AND outcome='no_op'",
                (batch.batch_id,),
            ).fetchone()[0]
            == 2
        )


def test_unavailable_source_and_missing_old_page_sources_remain_explicit(tmp_path):
    system = build_system(tmp_path)
    service, provenance, batch, entries, now = prepare(system)
    with system.database.transaction() as connection:
        service.organize(connection, "community", "first", batch.batch_id, entries, False, now)
        page = connection.execute(
            "SELECT * FROM memory_entries WHERE source_ref=?", (batch.batch_id,)
        ).fetchone()
        connection.execute(
            "UPDATE memory_segments SET summary_version='changed' WHERE segment_id=?",
            (entries[0].sources[0].source_id,),
        )
        sources = provenance.entry_sources(connection, "community", "first", page["memory_id"])
        assert sources[0]["readable"] is False and sources[0]["content"] is None
        connection.execute(
            "DELETE FROM memory_entry_sources WHERE memory_id=?", (page["memory_id"],)
        )
        assert provenance.entry_sources(connection, "community", "first", page["memory_id"]) == []
        with pytest.raises(ConflictError, match="supporting material is unavailable"):
            ViewMaterialPreparation().select(
                connection,
                "community",
                "first",
                datetime.now(UTC),
                {page["memory_id"]},
                max_count=32,
                max_chars=20000,
                batch_id="reading",
                version="1",
            )
