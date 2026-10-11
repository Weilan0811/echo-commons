from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, TypeAlias
from uuid import UUID

from echo_commons.shared.validation import (
    DomainInvariantError,
    TimeOrderError,
    optional_utc,
    require_non_empty,
    require_sequence,
    require_utc,
)

if TYPE_CHECKING:
    from echo_commons.modules.reflection.domain.node import ReflectionNodeTask


def _positive_integer(value: int, field_name: str) -> int:
    return require_sequence(value, field_name, minimum=1)


def _non_negative_integer(value: int, field_name: str) -> int:
    return require_sequence(value, field_name, minimum=0)


def _normalize_unique_strings(
    values: Sequence[str],
    field_name: str,
    *,
    minimum: int = 0,
) -> tuple[str, ...]:
    normalized = tuple(require_non_empty(value, field_name) for value in values)
    if len(normalized) < minimum:
        raise DomainInvariantError(f"{field_name} must contain at least {minimum} item(s)")
    if len(normalized) != len(set(normalized)):
        raise DomainInvariantError(f"{field_name} must not contain duplicates")
    return normalized


class FrozenPayload(Mapping[str, object]):
    """Small immutable JSON-like mapping used by ``ReflectionArtifact``.

    The Runtime may receive a model object or a plain mapping at the adapter
    boundary.  Storing a recursively frozen value here prevents an Artifact's
    content from changing after its fingerprint has been calculated.
    """

    __slots__ = ("_items", "_values")

    def __init__(self, value: Mapping[str, object]) -> None:
        if not isinstance(value, Mapping):
            raise DomainInvariantError("artifact payload must be a mapping")
        items: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise DomainInvariantError("artifact payload keys must be non-empty strings")
            items.append((key, _freeze_json_value(item)))
        items.sort(key=lambda item: item[0])
        self._items = tuple(items)
        self._values = dict(self._items)

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"FrozenPayload({self.to_dict()!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenPayload):
            return self._items == other._items
        if isinstance(other, Mapping):
            return self.to_dict() == dict(other)
        return NotImplemented

    def to_dict(self) -> dict[str, object]:
        return {key: _thaw_json_value(value) for key, value in self._items}


def _freeze_json_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DomainInvariantError("artifact payload numbers must be finite")
        return value
    if isinstance(value, Mapping):
        return FrozenPayload(value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json_value(item) for item in value)
    if isinstance(value, (UUID, datetime)):
        return str(value)
    raise DomainInvariantError("artifact payload must contain JSON-compatible values")


def _thaw_json_value(value: object) -> object:
    if isinstance(value, FrozenPayload):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value


def _canonical_json(value: object) -> str:
    if isinstance(value, FrozenPayload):
        value = value.to_dict()
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class ContentFingerprint:
    """Opaque content identity; ``from_value`` supplies deterministic hashing."""

    value: str

    def __post_init__(self) -> None:
        normalized = require_non_empty(self.value, "content fingerprint").strip()
        if any(char.isspace() for char in normalized):
            raise DomainInvariantError("content fingerprint must not contain whitespace")
        if len(normalized) > 200:
            raise DomainInvariantError("content fingerprint is too long")
        object.__setattr__(self, "value", normalized)

    @classmethod
    def from_value(cls, value: object) -> ContentFingerprint:
        normalized = value if isinstance(value, FrozenPayload) else _freeze_json_value(value)
        digest = hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()
        return cls(digest)

    @property
    def digest(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.value


def content_fingerprint(value: object) -> ContentFingerprint:
    """Return a stable SHA-256 fingerprint for a JSON-compatible value."""

    return ContentFingerprint.from_value(value)


@dataclass(frozen=True, slots=True)
class OutputContractRef:
    """Domain-side reference to one node output contract."""

    kind: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", require_non_empty(self.kind, "output contract kind"))
        object.__setattr__(
            self,
            "version",
            require_non_empty(self.version, "output contract version"),
        )

    @property
    def schema_id(self) -> str:
        return f"{self.kind}.{self.version}"

    @classmethod
    def from_schema_id(cls, schema_id: str) -> OutputContractRef:
        normalized = require_non_empty(schema_id, "output contract")
        kind, separator, version = normalized.rpartition(".")
        if not separator or not kind or not version:
            raise DomainInvariantError("output contract must use the 'kind.version' form")
        return cls(kind=kind, version=version)


@dataclass(frozen=True, slots=True)
class GraphSourceRef:
    """One immutable source identity included in a graph input boundary."""

    kind: str
    ref: str
    version: str

    def __post_init__(self) -> None:
        for field_name in ("kind", "ref", "version"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )

    @property
    def identity(self) -> tuple[str, str]:
        return self.kind, self.ref


@dataclass(frozen=True, slots=True)
class ReflectionSourceScope:
    """The frozen source boundary shared by all nodes of one graph run."""

    sources: tuple[GraphSourceRef, ...]

    def __post_init__(self) -> None:
        sources = tuple(self.sources)
        if not sources:
            raise DomainInvariantError("reflection source scope requires at least one source")
        if any(not isinstance(source, GraphSourceRef) for source in sources):
            raise DomainInvariantError("reflection source scope contains an invalid source")
        if len({source.identity for source in sources}) != len(sources):
            raise DomainInvariantError("reflection source scope sources must be unique")
        object.__setattr__(self, "sources", sources)

    @property
    def source_refs(self) -> tuple[str, ...]:
        return tuple(source.ref for source in self.sources)


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """One source or Artifact identity supporting a node output."""

    kind: str
    ref: str
    version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", require_non_empty(self.kind, "evidence kind"))
        object.__setattr__(self, "ref", require_non_empty(self.ref, "evidence ref"))
        if self.version is not None:
            object.__setattr__(
                self,
                "version",
                require_non_empty(self.version, "evidence version"),
            )

    @property
    def identity(self) -> tuple[str, str]:
        return self.kind, self.ref


def normalize_evidence_refs(values: Sequence[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    refs = tuple(values)
    if any(not isinstance(ref, EvidenceRef) for ref in refs):
        raise DomainInvariantError("evidence refs must contain EvidenceRef values")
    if len({ref.identity for ref in refs}) != len(refs):
        raise DomainInvariantError("evidence refs must not contain duplicates")
    return refs


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Stable reference passed between nodes instead of a mutable Artifact."""

    artifact_id: UUID
    content_fingerprint: ContentFingerprint | str

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, UUID):
            raise DomainInvariantError("artifact_id must be a UUID")
        fingerprint = (
            self.content_fingerprint
            if isinstance(self.content_fingerprint, ContentFingerprint)
            else ContentFingerprint(self.content_fingerprint)
        )
        object.__setattr__(self, "content_fingerprint", fingerprint)


@dataclass(frozen=True, slots=True)
class ReflectionLease:
    """Fencing identity attached to one claimed node task."""

    owner: str
    attempt: int
    generation: int
    expires_at_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "owner", require_non_empty(self.owner, "lease owner"))
        object.__setattr__(self, "attempt", _positive_integer(self.attempt, "lease attempt"))
        object.__setattr__(
            self,
            "generation",
            _positive_integer(self.generation, "lease generation"),
        )
        object.__setattr__(
            self,
            "expires_at_utc",
            require_utc(self.expires_at_utc, "lease expiry"),
        )

    def is_valid(
        self,
        *,
        owner: str,
        now_utc: datetime,
        attempt: int | None = None,
        generation: int | None = None,
    ) -> bool:
        if self.owner != owner:
            return False
        if attempt is not None and self.attempt != attempt:
            return False
        if generation is not None and self.generation != generation:
            return False
        return self.expires_at_utc > require_utc(now_utc, "now_utc")


Lease: TypeAlias = ReflectionLease


class ReflectionGraphKind(StrEnum):
    SEGMENT_REFLECT = "segment_reflect"
    CONTINUITY_COMPRESS = "continuity_compress"
    MEMORY_ORGANIZE = "memory_organize"
    DIARY_COMPOSE = "diary_compose"
    VIEW_REFRESH = "view_refresh"


class ReflectionNodeKind(StrEnum):
    SEGMENT_SUMMARY_PLAN = "segment_summary_plan"
    RELATIONSHIP_REFLECT = "relationship_reflect"
    STATE_REFLECT = "state_reflect"
    SEGMENT_AGGREGATE = "segment_aggregate"
    CONTINUITY_COMPRESS = "continuity_compress"
    CONTINUITY_AGGREGATE = "continuity_aggregate"
    PAGE_COMPOSE = "page_compose"
    GRAPH_EXTRACT = "graph_extract"
    MEMORY_AGGREGATE = "memory_aggregate"
    DIARY_COMPOSE = "diary_compose"
    DIARY_AGGREGATE = "diary_aggregate"
    VIEW_REFRESH_PLANNER = "view_refresh_planner"
    RELATIONSHIP_ATTITUDE_VIEW = "relationship_attitude_view"
    STATE_SUMMARY_VIEW = "state_summary_view"
    CORE_MEMORY_VIEW = "core_memory_view"
    VIEW_AGGREGATE = "view_aggregate"


class ReflectionExecutionKind(StrEnum):
    MODEL = "model"
    RUNTIME = "runtime"
    AGGREGATE = "aggregate"


class ReflectionDependencyMode(StrEnum):
    REQUIRED = "required"
    CONDITIONAL = "conditional"


class ReflectionGraphRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ReflectionDependency:
    """One fixed edge in a registered graph definition."""

    upstream_node_key: str
    downstream_node_key: str
    mode: ReflectionDependencyMode | str = ReflectionDependencyMode.REQUIRED

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "upstream_node_key",
            require_non_empty(self.upstream_node_key, "upstream node key"),
        )
        object.__setattr__(
            self,
            "downstream_node_key",
            require_non_empty(self.downstream_node_key, "downstream node key"),
        )
        if self.upstream_node_key == self.downstream_node_key:
            raise DomainInvariantError("a reflection dependency cannot point to itself")
        object.__setattr__(self, "mode", ReflectionDependencyMode(self.mode))

    @property
    def from_node_key(self) -> str:
        return self.upstream_node_key

    @property
    def to_node_key(self) -> str:
        return self.downstream_node_key

    @property
    def is_conditional(self) -> bool:
        return self.mode is ReflectionDependencyMode.CONDITIONAL


@dataclass(frozen=True, slots=True)
class ReflectionNodeDefinition:
    """Static contract and execution role of one fixed graph node."""

    node_key: str
    node_kind: ReflectionNodeKind | str
    input_contract: str
    output_contract: OutputContractRef
    execution_kind: ReflectionExecutionKind | str = ReflectionExecutionKind.MODEL
    required: bool = True
    allow_no_op: bool = True
    material_kinds: tuple[str, ...] = ()
    background_sections: tuple[str, ...] = ()
    prompt_resource: str | None = None
    action_kind: str | None = None
    fact_kind: str | None = None
    view_kind: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_key", require_non_empty(self.node_key, "node key"))
        node_kind = self.node_kind
        try:
            node_kind = ReflectionNodeKind(node_kind)
        except ValueError:
            node_kind = require_non_empty(str(node_kind), "node kind")
        object.__setattr__(self, "node_kind", node_kind)
        object.__setattr__(
            self,
            "input_contract",
            require_non_empty(self.input_contract, "input contract"),
        )
        if not isinstance(self.output_contract, OutputContractRef):
            raise DomainInvariantError("output_contract must be an OutputContractRef")
        execution_kind = self.execution_kind
        try:
            execution_kind = ReflectionExecutionKind(execution_kind)
        except ValueError:
            execution_kind = require_non_empty(str(execution_kind), "execution kind")
        object.__setattr__(self, "execution_kind", execution_kind)
        if not isinstance(self.required, bool) or not isinstance(self.allow_no_op, bool):
            raise DomainInvariantError("node required/allow_no_op flags must be booleans")


@dataclass(frozen=True, slots=True)
class ReflectionGraphDefinition:
    """A validated, immutable fixed topology; it contains no run state."""

    graph_kind: ReflectionGraphKind | str
    version: str
    nodes: tuple[ReflectionNodeDefinition, ...]
    dependencies: tuple[ReflectionDependency, ...] = ()
    aggregate_node_key: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "graph_kind", ReflectionGraphKind(self.graph_kind))
        object.__setattr__(self, "version", require_non_empty(self.version, "graph version"))
        nodes = tuple(self.nodes)
        if not nodes:
            raise DomainInvariantError("reflection graph must contain at least one node")
        if any(not isinstance(node, ReflectionNodeDefinition) for node in nodes):
            raise DomainInvariantError("reflection graph contains an invalid node definition")
        node_keys = tuple(node.node_key for node in nodes)
        if len(node_keys) != len(set(node_keys)):
            raise DomainInvariantError("reflection graph node keys must be unique")
        dependencies = tuple(self.dependencies)
        if any(not isinstance(edge, ReflectionDependency) for edge in dependencies):
            raise DomainInvariantError("reflection graph contains an invalid dependency")
        edge_keys = tuple(
            (edge.upstream_node_key, edge.downstream_node_key) for edge in dependencies
        )
        if len(edge_keys) != len(set(edge_keys)):
            raise DomainInvariantError("reflection graph dependencies must be unique")
        known_keys = set(node_keys)
        for edge in dependencies:
            if (
                edge.upstream_node_key not in known_keys
                or edge.downstream_node_key not in known_keys
            ):
                raise DomainInvariantError("reflection dependency references an unknown node")
        if self.aggregate_node_key is not None:
            aggregate_key = require_non_empty(self.aggregate_node_key, "aggregate node key")
            if aggregate_key not in known_keys:
                raise DomainInvariantError("aggregate node key is not part of the graph")
            object.__setattr__(self, "aggregate_node_key", aggregate_key)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "dependencies", dependencies)
        self._assert_acyclic()

    @property
    def node_keys(self) -> tuple[str, ...]:
        return tuple(node.node_key for node in self.nodes)

    @property
    def required_node_keys(self) -> tuple[str, ...]:
        return tuple(node.node_key for node in self.nodes if node.required)

    @property
    def root_node_keys(self) -> tuple[str, ...]:
        incoming = {edge.downstream_node_key for edge in self.dependencies}
        return tuple(key for key in self.node_keys if key not in incoming)

    @property
    def conditional_node_keys(self) -> tuple[str, ...]:
        keys = {
            edge.downstream_node_key
            for edge in self.dependencies
            if edge.mode is ReflectionDependencyMode.CONDITIONAL
        }
        return tuple(key for key in self.node_keys if key in keys and not self.node(key).required)

    def node(self, node_key: str) -> ReflectionNodeDefinition:
        for node in self.nodes:
            if node.node_key == node_key:
                return node
        raise DomainInvariantError(f"unknown reflection node: {node_key}")

    def dependencies_for(self, node_key: str) -> tuple[ReflectionDependency, ...]:
        self.node(node_key)
        return tuple(edge for edge in self.dependencies if edge.downstream_node_key == node_key)

    def dependents_of(self, node_key: str) -> tuple[ReflectionDependency, ...]:
        self.node(node_key)
        return tuple(edge for edge in self.dependencies if edge.upstream_node_key == node_key)

    def dependency_keys_for(self, node_key: str) -> tuple[str, ...]:
        return tuple(edge.upstream_node_key for edge in self.dependencies_for(node_key))

    def is_activated(self, node_key: str, activated_node_keys: Collection[str]) -> bool:
        dependencies = self.dependencies_for(node_key)
        if self.node(node_key).required or not any(edge.is_conditional for edge in dependencies):
            return True
        return node_key in activated_node_keys

    def dependencies_satisfied(
        self,
        node_key: str,
        *,
        completed_node_keys: Collection[str],
        activated_node_keys: Collection[str] = (),
    ) -> bool:
        if not self.is_activated(node_key, activated_node_keys):
            return False
        completed = set(completed_node_keys)
        activated = set(activated_node_keys)
        for edge in self.dependencies_for(node_key):
            if edge.is_conditional and edge.upstream_node_key not in activated:
                continue
            if edge.upstream_node_key not in completed:
                return False
        return True

    def can_complete(
        self,
        *,
        completed_node_keys: Collection[str],
        skipped_node_keys: Collection[str] = (),
    ) -> bool:
        completed = set(completed_node_keys)
        skipped = set(skipped_node_keys)
        known = set(self.node_keys)
        if not completed <= known or not skipped <= known or completed & skipped:
            raise DomainInvariantError("graph completion contains unknown or overlapping nodes")
        return set(self.required_node_keys) <= completed

    def _assert_acyclic(self) -> None:
        edges: dict[str, tuple[str, ...]] = {key: () for key in self.node_keys}
        for node_key in self.node_keys:
            edges[node_key] = tuple(
                edge.downstream_node_key for edge in self.dependents_of(node_key)
            )
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_key: str) -> None:
            if node_key in visiting:
                raise DomainInvariantError("reflection graph dependencies must be acyclic")
            if node_key in visited:
                return
            visiting.add(node_key)
            for downstream in edges[node_key]:
                visit(downstream)
            visiting.remove(node_key)
            visited.add(node_key)

        for node_key in self.node_keys:
            visit(node_key)


@dataclass(frozen=True, slots=True)
class ReflectionGraphRun:
    """Identity and aggregate lifecycle of one graph execution."""

    graph_run_id: UUID
    graph_kind: ReflectionGraphKind | str
    graph_version: str
    community_id: str
    character_id: str
    context_snapshot_id: str
    snapshot_fingerprint: ContentFingerprint | str
    source_scope: ReflectionSourceScope
    topology_node_keys: tuple[str, ...]
    required_node_keys: tuple[str, ...]
    created_at_utc: datetime
    updated_at_utc: datetime
    trace_id: UUID | None = None
    status: ReflectionGraphRunStatus | str = ReflectionGraphRunStatus.PENDING
    execution_generation: int = 0
    registered_node_keys: tuple[str, ...] = ()
    started_at_utc: datetime | None = None
    completed_at_utc: datetime | None = None
    last_error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.graph_run_id, UUID):
            raise DomainInvariantError("graph_run_id must be a UUID")
        graph_kind = self.graph_kind
        try:
            graph_kind = ReflectionGraphKind(graph_kind)
        except ValueError:
            graph_kind = require_non_empty(str(graph_kind), "graph kind")
        object.__setattr__(self, "graph_kind", graph_kind)
        object.__setattr__(
            self,
            "graph_version",
            require_non_empty(self.graph_version, "graph version"),
        )
        for field_name in ("community_id", "character_id", "context_snapshot_id"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )
        fingerprint = (
            self.snapshot_fingerprint
            if isinstance(self.snapshot_fingerprint, ContentFingerprint)
            else ContentFingerprint(self.snapshot_fingerprint)
        )
        object.__setattr__(self, "snapshot_fingerprint", fingerprint)
        if not isinstance(self.source_scope, ReflectionSourceScope):
            raise DomainInvariantError("source_scope must be a ReflectionSourceScope")
        topology = _normalize_unique_strings(
            self.topology_node_keys,
            "topology node keys",
            minimum=1,
        )
        required = _normalize_unique_strings(self.required_node_keys, "required node keys")
        if not set(required) <= set(topology):
            raise DomainInvariantError("required node keys must belong to the graph topology")
        registered = _normalize_unique_strings(self.registered_node_keys, "registered node keys")
        if not set(registered) <= set(topology):
            raise DomainInvariantError("registered node keys must belong to the graph topology")
        object.__setattr__(self, "topology_node_keys", topology)
        object.__setattr__(self, "required_node_keys", required)
        object.__setattr__(self, "registered_node_keys", registered)
        object.__setattr__(self, "status", ReflectionGraphRunStatus(self.status))
        object.__setattr__(
            self,
            "execution_generation",
            _non_negative_integer(self.execution_generation, "execution_generation"),
        )
        created = require_utc(self.created_at_utc, "created_at_utc")
        updated = require_utc(self.updated_at_utc, "updated_at_utc")
        started = optional_utc(self.started_at_utc, "started_at_utc")
        completed = optional_utc(self.completed_at_utc, "completed_at_utc")
        if updated < created:
            raise DomainInvariantError("updated_at_utc must not precede created_at_utc")
        if started is not None and started < created:
            raise DomainInvariantError("started_at_utc must not precede created_at_utc")
        if completed is not None and completed < created:
            raise DomainInvariantError("completed_at_utc must not precede created_at_utc")
        status = self.status
        if status in {
            ReflectionGraphRunStatus.COMPLETED,
            ReflectionGraphRunStatus.PARTIAL,
            ReflectionGraphRunStatus.FAILED,
            ReflectionGraphRunStatus.CANCELLED,
        }:
            if completed is None:
                raise DomainInvariantError("terminal graph run must have a completion time")
        elif completed is not None:
            raise DomainInvariantError("non-terminal graph run cannot have a completion time")
        if self.last_error_code is not None:
            object.__setattr__(
                self,
                "last_error_code",
                require_non_empty(self.last_error_code, "last_error_code"),
            )
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "updated_at_utc", updated)
        object.__setattr__(self, "started_at_utc", started)
        object.__setattr__(self, "completed_at_utc", completed)

    @classmethod
    def create(
        cls,
        *,
        graph_run_id: UUID,
        definition: ReflectionGraphDefinition,
        community_id: str,
        character_id: str,
        context_snapshot_id: str,
        snapshot_fingerprint: ContentFingerprint | str,
        source_scope: ReflectionSourceScope,
        now_utc: datetime,
        trace_id: UUID | None = None,
    ) -> ReflectionGraphRun:
        if not isinstance(definition, ReflectionGraphDefinition):
            raise DomainInvariantError("definition must be a ReflectionGraphDefinition")
        now = require_utc(now_utc, "now_utc")
        return cls(
            graph_run_id=graph_run_id,
            graph_kind=definition.graph_kind,
            graph_version=definition.version,
            community_id=community_id,
            character_id=character_id,
            context_snapshot_id=context_snapshot_id,
            snapshot_fingerprint=snapshot_fingerprint,
            source_scope=source_scope,
            topology_node_keys=definition.node_keys,
            required_node_keys=definition.required_node_keys,
            created_at_utc=now,
            updated_at_utc=now,
            trace_id=trace_id,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            ReflectionGraphRunStatus.COMPLETED,
            ReflectionGraphRunStatus.PARTIAL,
            ReflectionGraphRunStatus.FAILED,
            ReflectionGraphRunStatus.CANCELLED,
        }

    def register_node_key(
        self,
        node_key: str,
        *,
        now_utc: datetime | None = None,
    ) -> ReflectionGraphRun:
        key = require_non_empty(node_key, "node key")
        if key not in self.topology_node_keys:
            raise DomainInvariantError("node key is not part of the graph topology")
        if key in self.registered_node_keys:
            raise DomainInvariantError("node key is already registered for this graph run")
        now = self.updated_at_utc if now_utc is None else require_utc(now_utc, "now_utc")
        if now < self.updated_at_utc:
            raise TimeOrderError("graph time cannot move backwards")
        return replace(
            self,
            registered_node_keys=(*self.registered_node_keys, key),
            updated_at_utc=now,
        )

    def register_task(
        self,
        task: ReflectionNodeTask,
        *,
        now_utc: datetime | None = None,
    ) -> ReflectionGraphRun:
        """Register one NodeTask identity without storing its execution result."""

        if task.graph_run_id != self.graph_run_id:
            raise DomainInvariantError("node task belongs to a different graph run")
        return self.register_node_key(task.node_key, now_utc=now_utc)

    def start(self, *, now_utc: datetime) -> ReflectionGraphRun:
        now = self._forward_time(now_utc)
        if self.status not in {
            ReflectionGraphRunStatus.PENDING,
            ReflectionGraphRunStatus.RETRY_WAIT,
        }:
            raise DomainInvariantError("only a pending graph run can start")
        return replace(
            self,
            status=ReflectionGraphRunStatus.RUNNING,
            execution_generation=self.execution_generation + 1,
            started_at_utc=self.started_at_utc or now,
            updated_at_utc=now,
            last_error_code=None,
        )

    def complete(
        self,
        *,
        now_utc: datetime,
        completed_node_keys: Collection[str],
        skipped_node_keys: Collection[str] = (),
    ) -> ReflectionGraphRun:
        now = self._forward_time(now_utc)
        if self.status is not ReflectionGraphRunStatus.RUNNING:
            raise DomainInvariantError("only a running graph run can complete")
        completed = set(completed_node_keys)
        skipped = set(skipped_node_keys)
        if not self._can_complete(completed, skipped):
            raise DomainInvariantError("required reflection nodes are not complete")
        return replace(
            self,
            status=ReflectionGraphRunStatus.COMPLETED,
            completed_at_utc=now,
            updated_at_utc=now,
            last_error_code=None,
        )

    def partial(
        self,
        *,
        now_utc: datetime,
        completed_node_keys: Collection[str],
        failed_node_keys: Collection[str],
        skipped_node_keys: Collection[str] = (),
        error_code: str = "optional_node_failed",
    ) -> ReflectionGraphRun:
        now = self._forward_time(now_utc)
        if self.status is not ReflectionGraphRunStatus.RUNNING:
            raise DomainInvariantError("only a running graph run can become partial")
        completed = set(completed_node_keys)
        failed = set(failed_node_keys)
        skipped = set(skipped_node_keys)
        known = set(self.topology_node_keys)
        if not failed:
            raise DomainInvariantError("partial reflection graph must contain failed nodes")
        if not failed <= known or failed & completed or failed & skipped:
            raise DomainInvariantError("partial reflection graph contains invalid node sets")
        if failed & set(self.required_node_keys):
            raise DomainInvariantError("required reflection nodes cannot produce a partial graph")
        if not self._can_complete(completed, skipped):
            raise DomainInvariantError("required reflection nodes are not complete")
        return replace(
            self,
            status=ReflectionGraphRunStatus.PARTIAL,
            completed_at_utc=now,
            updated_at_utc=now,
            last_error_code=require_non_empty(error_code, "error_code"),
        )

    def retry(self, *, now_utc: datetime, error_code: str) -> ReflectionGraphRun:
        now = self._forward_time(now_utc)
        if self.status is not ReflectionGraphRunStatus.RUNNING:
            raise DomainInvariantError("only a running graph run can wait for retry")
        return replace(
            self,
            status=ReflectionGraphRunStatus.RETRY_WAIT,
            updated_at_utc=now,
            last_error_code=require_non_empty(error_code, "error_code"),
        )

    def reactivate(self, *, now_utc: datetime) -> ReflectionGraphRun:
        """Prepare a failed source run for another execution generation."""

        now = self._forward_time(now_utc)
        if self.status is not ReflectionGraphRunStatus.FAILED:
            raise DomainInvariantError("only a failed graph run can be reactivated")
        return replace(
            self,
            status=ReflectionGraphRunStatus.PENDING,
            completed_at_utc=None,
            updated_at_utc=now,
            last_error_code=None,
        )

    def fail(self, *, now_utc: datetime, error_code: str) -> ReflectionGraphRun:
        now = self._forward_time(now_utc)
        if self.status not in {
            ReflectionGraphRunStatus.RUNNING,
            ReflectionGraphRunStatus.RETRY_WAIT,
        }:
            raise DomainInvariantError("only an active graph run can fail")
        return replace(
            self,
            status=ReflectionGraphRunStatus.FAILED,
            completed_at_utc=now,
            updated_at_utc=now,
            last_error_code=require_non_empty(error_code, "error_code"),
        )

    def cancel(self, *, now_utc: datetime, reason_code: str = "cancelled") -> ReflectionGraphRun:
        now = self._forward_time(now_utc)
        if self.is_terminal:
            raise DomainInvariantError("a terminal graph run cannot be cancelled")
        return replace(
            self,
            status=ReflectionGraphRunStatus.CANCELLED,
            completed_at_utc=now,
            updated_at_utc=now,
            last_error_code=require_non_empty(reason_code, "reason_code"),
        )

    def _can_complete(self, completed: set[str], skipped: set[str]) -> bool:
        known = set(self.topology_node_keys)
        if not completed <= known or not skipped <= known or completed & skipped:
            raise DomainInvariantError("graph completion contains unknown or overlapping nodes")
        return set(self.required_node_keys) <= completed

    def _forward_time(self, value: datetime) -> datetime:
        now = require_utc(value, "now_utc")
        if now < self.updated_at_utc:
            raise TimeOrderError("graph time cannot move backwards")
        return now


@dataclass(frozen=True, slots=True)
class ReflectionArtifact:
    """Immutable successful output of one node attempt."""

    artifact_id: UUID
    graph_run_id: UUID
    node_task_id: UUID
    attempt: int
    node_input_fingerprint: ContentFingerprint | str
    output_contract: OutputContractRef
    payload: FrozenPayload | Mapping[str, object]
    evidence_refs: tuple[EvidenceRef, ...]
    created_at_utc: datetime
    invocation_id: UUID | None = None
    content_fingerprint: ContentFingerprint | str | None = None

    def __post_init__(self) -> None:
        for field_name in ("artifact_id", "graph_run_id", "node_task_id"):
            if not isinstance(getattr(self, field_name), UUID):
                raise DomainInvariantError(f"{field_name} must be a UUID")
        if self.invocation_id is not None and not isinstance(self.invocation_id, UUID):
            raise DomainInvariantError("invocation_id must be a UUID or None")
        object.__setattr__(self, "attempt", _positive_integer(self.attempt, "attempt"))
        input_fingerprint = (
            self.node_input_fingerprint
            if isinstance(self.node_input_fingerprint, ContentFingerprint)
            else ContentFingerprint(self.node_input_fingerprint)
        )
        object.__setattr__(self, "node_input_fingerprint", input_fingerprint)
        if not isinstance(self.output_contract, OutputContractRef):
            raise DomainInvariantError("output_contract must be an OutputContractRef")
        payload = (
            self.payload if isinstance(self.payload, FrozenPayload) else FrozenPayload(self.payload)
        )
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "evidence_refs", normalize_evidence_refs(self.evidence_refs))
        created = require_utc(self.created_at_utc, "created_at_utc")
        object.__setattr__(self, "created_at_utc", created)
        expected = content_fingerprint(
            {
                "output_contract": self.output_contract.schema_id,
                "payload": payload.to_dict(),
                "evidence_refs": [
                    {"kind": ref.kind, "ref": ref.ref, "version": ref.version}
                    for ref in self.evidence_refs
                ],
            }
        )
        supplied = self.content_fingerprint
        if supplied is None:
            supplied = expected
        elif not isinstance(supplied, ContentFingerprint):
            supplied = ContentFingerprint(supplied)
        if supplied != expected:
            raise DomainInvariantError("artifact content fingerprint does not match its content")
        object.__setattr__(self, "content_fingerprint", supplied)

    @classmethod
    def create(
        cls,
        *,
        artifact_id: UUID,
        graph_run_id: UUID,
        node_task_id: UUID,
        attempt: int,
        node_input_fingerprint: ContentFingerprint | str,
        output_contract: OutputContractRef,
        payload: Mapping[str, object],
        evidence_refs: Sequence[EvidenceRef] = (),
        created_at_utc: datetime,
        invocation_id: UUID | None = None,
    ) -> ReflectionArtifact:
        return cls(
            artifact_id=artifact_id,
            graph_run_id=graph_run_id,
            node_task_id=node_task_id,
            attempt=attempt,
            node_input_fingerprint=node_input_fingerprint,
            output_contract=output_contract,
            payload=payload,
            evidence_refs=tuple(evidence_refs),
            created_at_utc=created_at_utc,
            invocation_id=invocation_id,
        )

    @property
    def reference(self) -> ArtifactRef:
        return ArtifactRef(self.artifact_id, self.content_fingerprint)

    def is_same_content(self, other: ReflectionArtifact) -> bool:
        return (
            isinstance(other, ReflectionArtifact)
            and self.artifact_id == other.artifact_id
            and self.content_fingerprint == other.content_fingerprint
        )


def register_artifact(
    existing: ReflectionArtifact | None,
    incoming: ReflectionArtifact,
) -> ReflectionArtifact:
    """Idempotently register an Artifact, rejecting mutation under one ID."""

    if not isinstance(incoming, ReflectionArtifact):
        raise DomainInvariantError("incoming artifact must be a ReflectionArtifact")
    if existing is None:
        return incoming
    if not isinstance(existing, ReflectionArtifact):
        raise DomainInvariantError("existing artifact must be a ReflectionArtifact or None")
    if existing.artifact_id != incoming.artifact_id:
        raise DomainInvariantError("artifact registration identity does not match")
    if existing != incoming:
        raise DomainInvariantError("a registered artifact is immutable")
    return existing


def validate_unique_node_tasks(
    tasks: Sequence[ReflectionNodeTask],
    *,
    graph_run_id: UUID,
) -> tuple[str, ...]:
    """Validate one graph run has at most one task for each node key."""

    keys: list[str] = []
    for task in tasks:
        if task.graph_run_id != graph_run_id:
            raise DomainInvariantError("node task belongs to a different graph run")
        keys.append(require_non_empty(task.node_key, "node key"))
    if len(keys) != len(set(keys)):
        raise DomainInvariantError("a graph run cannot contain duplicate node keys")
    return tuple(keys)


def _contract(kind: str, version: str = "v1") -> OutputContractRef:
    return OutputContractRef(kind=kind, version=version)


def reflection_graph_definition(
    graph_kind: ReflectionGraphKind | str,
    *,
    version: str = "v1",
) -> ReflectionGraphDefinition:
    """Build one of the five fixed graph topologies specified by the baseline architecture."""

    kind = ReflectionGraphKind(graph_kind)
    node_contract = _contract("reflection_node")
    batch_contract = _contract("reflection_batch")
    if kind is ReflectionGraphKind.SEGMENT_REFLECT:
        nodes = (
            ReflectionNodeDefinition(
                "segment_summary_plan",
                ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
                "segment_context.v1",
                node_contract,
                material_kinds=("message", "thought"),
                background_sections=("state", "relationships", "memory"),
                prompt_resource="reflection/nodes/segment_summary_plan.md",
                action_kind="segment_summary",
            ),
            ReflectionNodeDefinition(
                "relationship_reflect",
                ReflectionNodeKind.RELATIONSHIP_REFLECT,
                "segment_summary_context.v1",
                node_contract,
                material_kinds=("message", "thought"),
                background_sections=("relationships",),
                prompt_resource="reflection/nodes/relationship_reflect.md",
                action_kind="relationship_reflection",
                required=False,
            ),
            ReflectionNodeDefinition(
                "state_reflect",
                ReflectionNodeKind.STATE_REFLECT,
                "segment_summary_context.v1",
                node_contract,
                material_kinds=("message", "thought"),
                background_sections=("state",),
                prompt_resource="reflection/nodes/state_reflect.md",
                action_kind="state_reflection",
                required=False,
            ),
            ReflectionNodeDefinition(
                "segment_aggregate",
                ReflectionNodeKind.SEGMENT_AGGREGATE,
                "reflection_artifacts.v1",
                batch_contract,
                execution_kind=ReflectionExecutionKind.AGGREGATE,
            ),
        )
        dependencies = (
            ReflectionDependency("segment_summary_plan", "relationship_reflect", "conditional"),
            ReflectionDependency("segment_summary_plan", "state_reflect", "conditional"),
            ReflectionDependency("segment_summary_plan", "segment_aggregate"),
            ReflectionDependency("relationship_reflect", "segment_aggregate", "conditional"),
            ReflectionDependency("state_reflect", "segment_aggregate", "conditional"),
        )
        return ReflectionGraphDefinition(kind, version, nodes, dependencies, "segment_aggregate")
    if kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
        nodes = (
            ReflectionNodeDefinition(
                "continuity_compress",
                ReflectionNodeKind.CONTINUITY_COMPRESS,
                "continuity_context.v1",
                node_contract,
                material_kinds=("segment_summary", "conversation_digest"),
                prompt_resource="reflection/nodes/continuity_compress.md",
                action_kind="continuity_digest",
            ),
            ReflectionNodeDefinition(
                "continuity_aggregate",
                ReflectionNodeKind.CONTINUITY_AGGREGATE,
                "reflection_artifacts.v1",
                batch_contract,
                execution_kind=ReflectionExecutionKind.AGGREGATE,
            ),
        )
        return ReflectionGraphDefinition(
            kind,
            version,
            nodes,
            (ReflectionDependency("continuity_compress", "continuity_aggregate"),),
            "continuity_aggregate",
        )
    if kind is ReflectionGraphKind.MEMORY_ORGANIZE:
        nodes = (
            ReflectionNodeDefinition(
                "page_compose",
                ReflectionNodeKind.PAGE_COMPOSE,
                "memory_organize_context.v1",
                node_contract,
                material_kinds=("segment_summary", "message", "thought", "author_chunk"),
                background_sections=("memory",),
                prompt_resource="reflection/nodes/page_compose.md",
                action_kind="long_term_memory_page",
            ),
            ReflectionNodeDefinition(
                "graph_extract",
                ReflectionNodeKind.GRAPH_EXTRACT,
                "memory_organize_context.v1",
                node_contract,
                material_kinds=("segment_summary", "message", "thought", "author_chunk"),
                background_sections=("memory",),
                prompt_resource="reflection/nodes/graph_extract.md",
                action_kind="graph_extraction",
            ),
            ReflectionNodeDefinition(
                "memory_aggregate",
                ReflectionNodeKind.MEMORY_AGGREGATE,
                "reflection_artifacts.v1",
                batch_contract,
                execution_kind=ReflectionExecutionKind.AGGREGATE,
            ),
        )
        return ReflectionGraphDefinition(
            kind,
            version,
            nodes,
            (
                ReflectionDependency("page_compose", "memory_aggregate"),
                ReflectionDependency("graph_extract", "memory_aggregate"),
            ),
            "memory_aggregate",
        )
    if kind is ReflectionGraphKind.DIARY_COMPOSE:
        nodes = (
            ReflectionNodeDefinition(
                "diary_compose",
                ReflectionNodeKind.DIARY_COMPOSE,
                "diary_context.v1",
                node_contract,
            ),
            ReflectionNodeDefinition(
                "diary_aggregate",
                ReflectionNodeKind.DIARY_AGGREGATE,
                "reflection_artifacts.v1",
                batch_contract,
                execution_kind=ReflectionExecutionKind.AGGREGATE,
            ),
        )
        return ReflectionGraphDefinition(
            kind,
            version,
            nodes,
            (ReflectionDependency("diary_compose", "diary_aggregate"),),
            "diary_aggregate",
        )
    nodes = (
        ReflectionNodeDefinition(
            "view_refresh_planner",
            ReflectionNodeKind.VIEW_REFRESH_PLANNER,
            "change_set.v1",
            node_contract,
            material_kinds=("formal_fact",),
            execution_kind=ReflectionExecutionKind.RUNTIME,
        ),
        ReflectionNodeDefinition(
            "relationship_attitude_view",
            ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW,
            "view_refresh_request.v1",
            node_contract,
            material_kinds=("formal_fact",),
            prompt_resource="reflection/nodes/relationship_attitude_view.md",
            action_kind="view_refresh",
            fact_kind="relationship",
            view_kind="relationship_attitude",
            required=False,
        ),
        ReflectionNodeDefinition(
            "state_summary_view",
            ReflectionNodeKind.STATE_SUMMARY_VIEW,
            "view_refresh_request.v1",
            node_contract,
            material_kinds=("formal_fact",),
            prompt_resource="reflection/nodes/state_summary_view.md",
            action_kind="view_refresh",
            fact_kind="character_state",
            view_kind="state_summary",
            required=False,
        ),
        ReflectionNodeDefinition(
            "core_memory_view",
            ReflectionNodeKind.CORE_MEMORY_VIEW,
            "view_refresh_request.v1",
            node_contract,
            material_kinds=("formal_fact",),
            background_sections=("memory",),
            prompt_resource="reflection/nodes/core_memory_view.md",
            action_kind="view_refresh",
            fact_kind="memory_entry",
            view_kind="core_memory",
            required=False,
        ),
        ReflectionNodeDefinition(
            "view_aggregate",
            ReflectionNodeKind.VIEW_AGGREGATE,
            "reflection_artifacts.v1",
            batch_contract,
            execution_kind=ReflectionExecutionKind.AGGREGATE,
        ),
    )
    dependencies = (
        ReflectionDependency("view_refresh_planner", "relationship_attitude_view", "conditional"),
        ReflectionDependency("view_refresh_planner", "state_summary_view", "conditional"),
        ReflectionDependency("view_refresh_planner", "core_memory_view", "conditional"),
        ReflectionDependency("view_refresh_planner", "view_aggregate"),
        ReflectionDependency("relationship_attitude_view", "view_aggregate", "conditional"),
        ReflectionDependency("state_summary_view", "view_aggregate", "conditional"),
        ReflectionDependency("core_memory_view", "view_aggregate", "conditional"),
    )
    return ReflectionGraphDefinition(kind, version, nodes, dependencies, "view_aggregate")
