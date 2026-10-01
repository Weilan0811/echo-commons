from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import aiosqlite

from echo_server.agents.contracts import (
    CapabilityDefinition,
    CapabilityView,
    GraphContextSnapshot,
    GraphSourceReference,
    GraphSourceScope,
    IdentityContext,
)
from echo_server.agents.contracts.reflection_context import (
    ReflectionContext,
    ReflectionSourceMaterial,
    ReflectionWindowContext,
)
from echo_server.domain.reflection_graph import ReflectionSourceScope
from echo_server.runtime.reflection.identity_context import build_identity_context

if TYPE_CHECKING:
    from echo_server.runtime.modules import ReflectionModule


@dataclass(frozen=True, slots=True)
class SnapshotBuildContext:
    now_utc: datetime
    connection: aiosqlite.Connection


@dataclass(frozen=True, slots=True)
class SnapshotSourceBuild:
    account_id: str
    character_id: str
    source_scope: ReflectionSourceScope
    materials: tuple[ReflectionSourceMaterial, ...]
    window: ReflectionWindowContext


@dataclass(frozen=True, slots=True)
class GraphSnapshotBuild:
    snapshot: GraphContextSnapshot
    source_scope: ReflectionSourceScope


class GraphSnapshotAssembler:
    """组装所有反思任务共用的身份、状态和来源快照。"""

    def __init__(
        self,
        runtime: ReflectionModule,
        *,
        max_materials: int,
        max_material_chars: int,
    ) -> None:
        self.runtime = runtime
        self.max_materials = max_materials
        self.max_material_chars = max_material_chars

    async def assemble(
        self,
        source: SnapshotSourceBuild,
        *,
        context: SnapshotBuildContext,
    ) -> GraphSnapshotBuild:
        source_snapshot = await self.runtime.context_source.load_character(
            source.account_id,
            source.character_id,
            now_utc=context.now_utc,
            connection=context.connection,
            memory_limit=min(
                self.runtime.settings.resident_memory_limit,
                self.max_materials,
            ),
        )
        identity = build_identity_context(
            self.runtime.identity_catalog,
            source.character_id,
        )
        capability_view = CapabilityView(
            available=tuple(
                CapabilityDefinition(
                    name=capability.name,
                    description=capability.description,
                    parameters=dict(capability.parameters),
                    action_kind=capability.action_kind,
                )
                for capability in sorted(
                    self.runtime.identity_catalog.character(source.character_id).capabilities,
                    key=lambda item: item.name,
                )
            )
        )
        reflection_context = ReflectionContext(
            character_id=source.character_id,
            now_utc=context.now_utc,
            identity=identity,
            character_state=source_snapshot.character_state,
            relationship_state=source_snapshot.relationship_state,
            memory_context=source_snapshot.memory_context,
            window=source.window,
            materials=source.materials,
        )
        contract_source_scope = GraphSourceScope(
            sources=tuple(
                GraphSourceReference(
                    kind=item.kind,
                    ref=item.ref,
                    version=item.version,
                )
                for item in source.source_scope.sources
            )
        )
        snapshot = GraphContextSnapshot.create(
            snapshot_id=_snapshot_id(
                account_id=source.account_id,
                character_id=source.character_id,
                identity=identity,
                source_versions=source_snapshot.source_versions,
                source_scope=contract_source_scope,
                materials=source.materials,
            ),
            account_id=source.account_id,
            character_id=source.character_id,
            context=reflection_context,
            capability_view=capability_view,
            source_scope=contract_source_scope,
        )
        return GraphSnapshotBuild(
            snapshot=snapshot,
            source_scope=source.source_scope,
        )


def bound_materials(
    materials: Iterable[ReflectionSourceMaterial],
    *,
    max_materials: int,
    max_material_chars: int,
    required_source_refs: frozenset[str],
) -> tuple[ReflectionSourceMaterial, ...]:
    bounded: list[ReflectionSourceMaterial] = []
    used_chars = 0
    seen: set[str] = set()
    for material in materials:
        if material.source_ref in seen:
            continue
        if len(bounded) >= max_materials or used_chars + len(material.content) > max_material_chars:
            break
        bounded.append(material)
        seen.add(material.source_ref)
        used_chars += len(material.content)
    if not required_source_refs.issubset(seen):
        raise LookupError("reflection_snapshot_material_budget_exceeded")
    return tuple(bounded)


def _snapshot_id(
    *,
    account_id: str,
    character_id: str,
    identity: IdentityContext,
    source_versions: tuple[object, ...],
    source_scope: GraphSourceScope,
    materials: tuple[ReflectionSourceMaterial, ...],
) -> str:
    payload = {
        "schema": 2,
        "account_id": account_id,
        "character_id": character_id,
        "identity": identity.model_dump(mode="json"),
        "state_sources": [(item.source, item.version) for item in source_versions],
        "source_scope": [(item.kind, item.ref, item.version) for item in source_scope.sources],
        "materials": _materials_version(materials),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return f"reflection-snapshot-v2:{digest}"


def _materials_version(materials: tuple[ReflectionSourceMaterial, ...]) -> str:
    payload = [
        (
            item.source_ref,
            item.content_version,
            item.content,
            item.occurred_at_utc.isoformat() if item.occurred_at_utc else None,
        )
        for item in materials
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]


__all__ = [
    "GraphSnapshotAssembler",
    "GraphSnapshotBuild",
    "SnapshotBuildContext",
    "SnapshotSourceBuild",
    "bound_materials",
]
