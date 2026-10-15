from fastapi.testclient import TestClient
from support.application import settings_for
from support.initialization import create_authored

from echo_commons.app.main import create_app
from echo_commons.modules.memory.domain.organization import FactAdd, MemoryFactContent
from echo_commons.modules.reflection.budget import ReflectionBudget
from echo_commons.modules.reflection.contracts.candidates import (
    MemoryFactCandidate,
    ReflectionBatchProposal,
)
from echo_commons.modules.reflection.tasks.graph_review import GraphReview


def test_author_budget_and_compact_provenance_preserve_business_content(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        app = create_authored(client)
        search = client.get("/internal/communities", params={"q": "community"})
        assert [item["community_id"] for item in search.json()["items"]] == ["community"]
        assert (
            client.get("/internal/communities", params={"q": "missing-community"}).json()["items"]
            == []
        )
        public = client.get("/api/communities/community/characters", params={"player_id": "alice"})
        assert "memory_error_code" not in public.json()[0]
        managed = client.get("/internal/communities/community/characters")
        assert "memory_error_code" in managed.json()["items"][0]
        index = client.get(
            "/internal/characters/authored/memory-index", params={"community_id": "community"}
        )
        assert set(index.json()) == {
            "documents",
            "vectors",
            "vector_enabled",
            "model_identity",
            "failures",
        }
        with app.database.read() as connection:
            row = connection.execute(
                "SELECT organization_run_id FROM memory_initializations "
                "WHERE character_id='authored'"
            ).fetchone()
            snapshot = app.reflection.runs.snapshot(connection, "community", "authored", row[0])
        refs = tuple(item.evidence_ref for item in snapshot.materials)
        candidate = MemoryFactCandidate(
            source_refs=refs,
            operation=FactAdd(
                local_key="fact1",
                evidence_refs=refs,
                fact=MemoryFactContent(topic="旧钟", content="外婆教我修理旧钟。"),
            ),
        )
        batch = ReflectionBatchProposal(candidates=(candidate,) * 16)
        compact = batch.compact_dump()
        assert compact["source_groups"] == [list(refs)]
        assert all(item["source_group"] == 0 for item in compact["candidates"])
        assert ReflectionBatchProposal.model_validate(compact) == batch
        assert ReflectionBatchProposal.model_validate(batch.model_dump()) == batch
        assert batch.content_chars < len(batch.model_dump_json())
        budget = ReflectionBudget()
        assert GraphReview(64, 20000, budget).check(snapshot, batch) is None
        larger = snapshot.model_copy(
            update={
                "materials": tuple(
                    item.model_copy(update={"content": item.content * 100})
                    for item in snapshot.materials
                )
            }
        )
        assert budget.limits(larger)[1] > budget.limits(snapshot)[1]
        assert budget.limits(larger)[1] <= budget.initialization_max_output_chars
        restricted = ReflectionBudget(initialization_max_candidates=8)
        assert (
            GraphReview(64, 20000, restricted).check(snapshot, batch)
            == "reflection_batch_too_large"
        )
