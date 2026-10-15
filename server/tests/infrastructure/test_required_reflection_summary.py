from datetime import UTC, datetime

import pytest
from support.memory import sealing
from support.messages import build_system, send
from support.reflection import build_reflection

from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.memory.services.continuity import MemoryContinuity
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.reflection.contracts.candidates import ReflectionBatchProposal
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.graph_review import GraphReview
from echo_commons.shared.errors import ConflictError


def test_segment_allows_no_op_but_continuity_requires_digest(tmp_path):
    system = build_system(tmp_path)
    message = send(system, "我们答应明天一起做饭。")
    segment = sealing(system).seal("community", "first")
    _, coordinator = build_reflection(system)
    run = coordinator.start_segment("community", "first", segment.segment_id)
    review = GraphReview(64, 20000)
    no_op = ReflectionBatchProposal(outcome="no_op", no_op_reason="没有可记录内容")
    with system.database.read() as connection:
        snapshot = RunRepository().snapshot(connection, "community", "first", str(run.graph_run_id))
        assert review.check(snapshot, no_op) is None
    provenance = MemoryProvenanceRepository()
    ingestion = MemoryIngestion(SegmentRepository(), CoverageRepository())
    with system.database.transaction() as connection:
        ingestion.ingest(
            connection,
            "community",
            "first",
            segment.segment_id,
            "我记得对方说：" + message.text,
            datetime.now(UTC),
        )
    batches = SummaryBatches(
        system.database,
        InstanceRepository(),
        ConversationRepository(),
        system.world,
        provenance,
        max_materials=256,
        max_chars=20000,
    )
    batch = batches.freeze(
        "community",
        "first",
        SummaryConsumer.CONTINUITY,
    )
    run = coordinator.start_summary(
        "community", "first", batch.batch_id, ReflectionGraphKind.CONTINUITY_COMPRESS
    )
    with system.database.read() as connection:
        snapshot = RunRepository().snapshot(connection, "community", "first", str(run.graph_run_id))
        assert review.check(snapshot, no_op) == "reflection_digest_required"
    continuity = MemoryContinuity(provenance)
    with pytest.raises(ConflictError), system.database.transaction() as connection:
        continuity.compress(
            connection,
            "community",
            "first",
            batch.batch_id,
            None,
            datetime.now(UTC),
        )
    with system.database.read() as connection:
        assert provenance.digest_for_batch(connection, batch) is None
    with system.database.transaction() as connection:
        continuity.compress(
            connection,
            "community",
            "first",
            batch.batch_id,
            "我记得明天做饭的约定。",
            datetime.now(UTC),
        )
    following = send(system, "明天做饭时我会带上蔬菜。")
    segment = sealing(system).seal("community", "first")
    with system.database.transaction() as connection:
        ingestion.ingest(
            connection,
            "community",
            "first",
            segment.segment_id,
            "我记得对方说：" + following.text,
            datetime.now(UTC),
        )
    next_batch = batches.freeze(
        "community",
        "first",
        SummaryConsumer.CONTINUITY,
    )
    with system.database.transaction() as connection:
        previous = provenance.digest_for_batch(connection, batch)
        assert next_batch.previous_digest_ids == (previous["digest_id"],)
        continuity.compress(
            connection,
            "community",
            "first",
            next_batch.batch_id,
            "我记得明天做饭，对方会带蔬菜。",
            datetime.now(UTC),
        )
        assert segment.segment_id in provenance.digest_segments(
            connection, provenance.digest_for_batch(connection, next_batch)["digest_id"]
        )
