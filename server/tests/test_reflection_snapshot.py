from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from support_agent_context import build_test_snapshot

from echo_commons.agents.contracts import (
    CapabilityView,
    GraphContextSnapshot,
    GraphSourceReference,
    GraphSourceScope,
    ReflectionContext,
    ReflectionSourceMaterial,
    ReflectionWindowContext,
)


def _reflection_context(
    *, now_utc: datetime, material_time: datetime | None = None
) -> ReflectionContext:
    snapshot = build_test_snapshot(now_utc=now_utc)
    return ReflectionContext(
        character_id=snapshot.character_id,
        now_utc=now_utc,
        identity=snapshot.identity,
        character_state=snapshot.character_state,
        relationship_state=snapshot.relationship_state,
        memory_context=snapshot.memory_context,
        window=ReflectionWindowContext(
            first_message_sequence=1,
            last_message_sequence=1,
        ),
        materials=(
            ReflectionSourceMaterial(
                source_ref="message:1",
                source_kind="conversation_player",
                content="一段来源材料",
                content_version="message-v1",
                occurred_at_utc=material_time or now_utc,
            ),
        ),
    )


def _source_scope() -> GraphSourceScope:
    return GraphSourceScope(
        sources=(
            GraphSourceReference(
                kind="conversation_player",
                ref="message:1",
                version="message-v1",
            ),
        ),
    )


def test_graph_snapshot_fingerprint_excludes_snapshot_id_and_clock() -> None:
    base_context = _reflection_context(
        now_utc=datetime(2026, 9, 19, 12, tzinfo=UTC),
        material_time=datetime(2026, 9, 19, 11, tzinfo=UTC),
    )
    first = GraphContextSnapshot.create(
        snapshot_id="snapshot-a",
        account_id="local-player",
        character_id="xiaojin",
        context=base_context,
        capability_view=CapabilityView(),
        source_scope=_source_scope(),
    )
    second = GraphContextSnapshot.create(
        snapshot_id="snapshot-b",
        account_id="local-player",
        character_id="xiaojin",
        context=base_context.model_copy(
            update={
                "now_utc": datetime(2026, 9, 19, 12, tzinfo=UTC) + timedelta(seconds=30),
            }
        ),
        capability_view=CapabilityView(),
        source_scope=_source_scope(),
    )

    assert first.snapshot_fingerprint == second.snapshot_fingerprint
    assert first.snapshot_id != second.snapshot_id


def test_graph_snapshot_rejects_duplicate_source_identity() -> None:
    with pytest.raises(ValidationError, match="sources must be unique"):
        GraphSourceScope(
            sources=(
                GraphSourceReference(kind="message", ref="message:1", version="v1"),
                GraphSourceReference(kind="message", ref="message:1", version="v2"),
            ),
        )


def test_graph_snapshot_rejects_forged_fingerprint() -> None:
    context = _reflection_context(
        now_utc=datetime(2026, 9, 19, 12, tzinfo=UTC),
    )
    with pytest.raises(ValidationError, match="fingerprint"):
        GraphContextSnapshot(
            snapshot_id="snapshot-a",
            snapshot_fingerprint="forged",
            account_id="local-player",
            character_id="xiaojin",
            context=context,
            capability_view=CapabilityView(),
            source_scope=_source_scope(),
        )
