from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from echo_commons.modules.reflection.domain.graph import (
    ArtifactRef,
    ContentFingerprint,
    OutputContractRef,
    ReflectionArtifact,
    ReflectionLease,
    ReflectionNodeKind,
)
from echo_commons.shared.validation import DomainInvariantError, require_non_empty, require_utc


class ReflectionNodeTaskStatus(StrEnum):
    """Lifecycle values persisted for one graph node."""

    PENDING = "pending"
    PROCESSING = "processing"
    RETRY_WAIT = "retry_wait"
    SKIPPED = "skipped"
    COMPLETED = "completed"
    FAILED = "failed"


def _integer(value: int, field_name: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise DomainInvariantError(f"{field_name} must be an integer >= {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class ReflectionNodeTask:
    """Scheduling and lease state for one fixed graph node.

    The task stores only the node input fingerprint and predecessor Artifact
    references. Node output is immutable and lives in ReflectionArtifact.
    """

    task_id: UUID
    graph_run_id: UUID
    node_key: str
    node_kind: ReflectionNodeKind | str
    dependency_keys: tuple[str, ...]
    node_input_fingerprint: ContentFingerprint | str
    output_contract: OutputContractRef
    available_at_utc: datetime
    created_at_utc: datetime
    updated_at_utc: datetime
    status: str = ReflectionNodeTaskStatus.PENDING
    activated: bool = True
    input_artifact_refs: tuple[ArtifactRef, ...] = ()
    attempt_count: int = 0
    lease_generation: int = 0
    lease: ReflectionLease | None = None
    artifact_id: UUID | None = None
    last_error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, UUID) or not isinstance(self.graph_run_id, UUID):
            raise DomainInvariantError("task_id and graph_run_id must be UUIDs")
        object.__setattr__(self, "node_key", require_non_empty(self.node_key, "node key"))
        try:
            node_kind = ReflectionNodeKind(self.node_kind)
        except ValueError:
            node_kind = require_non_empty(str(self.node_kind), "node kind")
        object.__setattr__(self, "node_kind", node_kind)
        dependencies = tuple(
            require_non_empty(value, "dependency key") for value in self.dependency_keys
        )
        if len(dependencies) != len(set(dependencies)):
            raise DomainInvariantError("node task dependency keys must be unique")
        if self.node_key in dependencies:
            raise DomainInvariantError("node task cannot depend on itself")
        object.__setattr__(self, "dependency_keys", dependencies)
        fingerprint = (
            self.node_input_fingerprint
            if isinstance(self.node_input_fingerprint, ContentFingerprint)
            else ContentFingerprint(self.node_input_fingerprint)
        )
        object.__setattr__(self, "node_input_fingerprint", fingerprint)
        if not isinstance(self.output_contract, OutputContractRef):
            raise DomainInvariantError("output_contract must be an OutputContractRef")
        refs = tuple(self.input_artifact_refs)
        if any(not isinstance(ref, ArtifactRef) for ref in refs):
            raise DomainInvariantError("input_artifact_refs must contain ArtifactRef values")
        if len({ref.artifact_id for ref in refs}) != len(refs):
            raise DomainInvariantError("input_artifact_refs must not contain duplicates")
        object.__setattr__(self, "input_artifact_refs", refs)
        if not isinstance(self.activated, bool):
            raise DomainInvariantError("activated must be a boolean")
        object.__setattr__(self, "status", ReflectionNodeTaskStatus(str(self.status)))
        object.__setattr__(
            self,
            "attempt_count",
            _integer(self.attempt_count, "attempt_count"),
        )
        object.__setattr__(
            self,
            "lease_generation",
            _integer(self.lease_generation, "lease_generation"),
        )
        if self.artifact_id is not None and not isinstance(self.artifact_id, UUID):
            raise DomainInvariantError("artifact_id must be a UUID or None")
        if self.last_error_code is not None:
            object.__setattr__(
                self,
                "last_error_code",
                require_non_empty(self.last_error_code, "last_error_code"),
            )
        available = require_utc(self.available_at_utc, "available_at_utc")
        created = require_utc(self.created_at_utc, "created_at_utc")
        updated = require_utc(self.updated_at_utc, "updated_at_utc")
        if available < created:
            raise DomainInvariantError("available_at_utc must not precede created_at_utc")
        if updated < created:
            raise DomainInvariantError("updated_at_utc must not precede created_at_utc")
        if self.status is ReflectionNodeTaskStatus.PROCESSING:
            if self.lease is None or self.lease.expires_at_utc <= updated:
                raise DomainInvariantError("processing node task must have a future lease")
            if self.lease.attempt != self.attempt_count:
                raise DomainInvariantError("node task lease attempt does not match task attempt")
            if self.lease.generation != self.lease_generation:
                raise DomainInvariantError("node task lease generation does not match task fence")
        elif self.lease is not None:
            raise DomainInvariantError("only a processing node task may have a lease")
        if self.status is ReflectionNodeTaskStatus.COMPLETED and self.artifact_id is None:
            raise DomainInvariantError("completed node task must reference an Artifact")
        if self.status is not ReflectionNodeTaskStatus.COMPLETED and self.artifact_id is not None:
            raise DomainInvariantError("only a completed node task may reference an Artifact")
        object.__setattr__(self, "available_at_utc", available)
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "updated_at_utc", updated)

    @classmethod
    def create(
        cls,
        *,
        task_id: UUID,
        graph_run_id: UUID,
        node_key: str,
        node_kind: ReflectionNodeKind | str,
        dependency_keys: Sequence[str],
        node_input_fingerprint: ContentFingerprint | str,
        output_contract: OutputContractRef,
        now_utc: datetime,
        input_artifact_refs: Sequence[ArtifactRef] = (),
        activated: bool = True,
    ) -> ReflectionNodeTask:
        now = require_utc(now_utc, "now_utc")
        return cls(
            task_id=task_id,
            graph_run_id=graph_run_id,
            node_key=node_key,
            node_kind=node_kind,
            dependency_keys=tuple(dependency_keys),
            node_input_fingerprint=node_input_fingerprint,
            output_contract=output_contract,
            available_at_utc=now,
            created_at_utc=now,
            updated_at_utc=now,
            input_artifact_refs=tuple(input_artifact_refs),
            activated=activated,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            ReflectionNodeTaskStatus.COMPLETED,
            ReflectionNodeTaskStatus.FAILED,
            ReflectionNodeTaskStatus.SKIPPED,
        }

    @property
    def lease_owner(self) -> str | None:
        return self.lease.owner if self.lease is not None else None

    @property
    def lease_until_utc(self) -> datetime | None:
        return self.lease.expires_at_utc if self.lease is not None else None

    def is_claimable(
        self,
        *,
        completed_node_keys: Collection[str],
        resolved_node_keys: Collection[str] = (),
    ) -> bool:
        if not self.activated or self.status not in {
            ReflectionNodeTaskStatus.PENDING,
            ReflectionNodeTaskStatus.RETRY_WAIT,
        }:
            return False
        return set(self.dependency_keys) <= (set(completed_node_keys) | set(resolved_node_keys))

    def activate(self, *, now_utc: datetime) -> ReflectionNodeTask:
        now = self._forward_time(now_utc)
        if self.activated:
            raise DomainInvariantError("node task is already activated")
        if self.status not in {
            ReflectionNodeTaskStatus.PENDING,
            ReflectionNodeTaskStatus.RETRY_WAIT,
        }:
            raise DomainInvariantError("only an unclaimed node task can be activated")
        return replace(self, activated=True, available_at_utc=now, updated_at_utc=now)

    def bind_input_artifacts(
        self,
        *,
        input_artifact_refs: Sequence[ArtifactRef],
        node_input_fingerprint: ContentFingerprint | str,
        now_utc: datetime,
    ) -> ReflectionNodeTask:
        now = self._forward_time(now_utc)
        if self.status not in {
            ReflectionNodeTaskStatus.PENDING,
            ReflectionNodeTaskStatus.RETRY_WAIT,
        }:
            raise DomainInvariantError("only an unclaimed node task can bind input Artifacts")
        refs = tuple(input_artifact_refs)
        if any(not isinstance(ref, ArtifactRef) for ref in refs):
            raise DomainInvariantError("input_artifact_refs must contain ArtifactRef values")
        if len({ref.artifact_id for ref in refs}) != len(refs):
            raise DomainInvariantError("input_artifact_refs must not contain duplicates")
        fingerprint = (
            node_input_fingerprint
            if isinstance(node_input_fingerprint, ContentFingerprint)
            else ContentFingerprint(node_input_fingerprint)
        )
        return replace(
            self,
            input_artifact_refs=refs,
            node_input_fingerprint=fingerprint,
            available_at_utc=now,
            updated_at_utc=now,
            last_error_code=None,
        )

    def claim(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        lease_until_utc: datetime,
        completed_node_keys: Collection[str] = (),
        resolved_node_keys: Collection[str] = (),
    ) -> ReflectionNodeTask:
        owner = require_non_empty(worker_id, "worker_id")
        now = self._forward_time(now_utc)
        lease_until = require_utc(lease_until_utc, "lease_until_utc")
        if self.status not in {
            ReflectionNodeTaskStatus.PENDING,
            ReflectionNodeTaskStatus.RETRY_WAIT,
        }:
            raise DomainInvariantError("only pending or retry-wait node tasks can be claimed")
        if not self.activated:
            raise DomainInvariantError("conditional node task has not been activated")
        if not self.is_claimable(
            completed_node_keys=completed_node_keys,
            resolved_node_keys=resolved_node_keys,
        ):
            raise DomainInvariantError("node task dependencies are not complete")
        if now < self.available_at_utc:
            raise DomainInvariantError("node task is not available yet")
        if lease_until <= now:
            raise DomainInvariantError("lease must expire in the future")
        next_attempt = self.attempt_count + 1
        next_generation = self.lease_generation + 1
        return replace(
            self,
            status=ReflectionNodeTaskStatus.PROCESSING,
            attempt_count=next_attempt,
            lease_generation=next_generation,
            lease=ReflectionLease(
                owner=owner,
                attempt=next_attempt,
                generation=next_generation,
                expires_at_utc=lease_until,
            ),
            updated_at_utc=now,
            last_error_code=None,
        )

    def has_valid_lease(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
    ) -> bool:
        return bool(
            self.status is ReflectionNodeTaskStatus.PROCESSING
            and self.lease is not None
            and self.lease.is_valid(
                owner=worker_id,
                now_utc=now_utc,
                attempt=attempt_count,
                generation=lease_generation,
            )
        )

    def complete(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        artifact: ReflectionArtifact | ArtifactRef | UUID,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
    ) -> ReflectionNodeTask:
        now = self._forward_time(now_utc)
        self._require_active_lease(
            worker_id=worker_id,
            now=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        return replace(
            self,
            status=ReflectionNodeTaskStatus.COMPLETED,
            lease=None,
            artifact_id=self._artifact_id_for_completion(artifact),
            last_error_code=None,
            updated_at_utc=now,
        )

    def retry_or_fail(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        available_at_utc: datetime,
        error_code: str,
        max_attempts: int,
        terminal: bool = False,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
    ) -> ReflectionNodeTask:
        now = self._forward_time(now_utc)
        available = require_utc(available_at_utc, "available_at_utc")
        if available < now:
            raise DomainInvariantError("retry availability cannot be earlier than now")
        self._require_active_lease(
            worker_id=worker_id,
            now=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        status = (
            ReflectionNodeTaskStatus.FAILED
            if terminal or self.attempt_count >= _integer(max_attempts, "max_attempts", minimum=1)
            else ReflectionNodeTaskStatus.RETRY_WAIT
        )
        return replace(
            self,
            status=status,
            available_at_utc=available,
            lease=None,
            last_error_code=require_non_empty(error_code, "error_code"),
            updated_at_utc=now,
        )

    def recover_expired(self, *, now_utc: datetime, max_attempts: int) -> ReflectionNodeTask:
        now = self._forward_time(now_utc)
        if self.status is not ReflectionNodeTaskStatus.PROCESSING or self.lease is None:
            raise DomainInvariantError("only a processing node task can recover an expired lease")
        if self.lease.expires_at_utc > now:
            raise DomainInvariantError("node task lease has not expired")
        return replace(
            self,
            status=(
                ReflectionNodeTaskStatus.FAILED
                if self.attempt_count >= _integer(max_attempts, "max_attempts", minimum=1)
                else ReflectionNodeTaskStatus.RETRY_WAIT
            ),
            available_at_utc=now,
            lease=None,
            last_error_code=self.last_error_code or "lease_expired",
            updated_at_utc=now,
        )

    def renew_lease(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        lease_until_utc: datetime,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
    ) -> ReflectionNodeTask:
        now = self._forward_time(now_utc)
        lease_until = require_utc(lease_until_utc, "lease_until_utc")
        self._require_active_lease(
            worker_id=worker_id,
            now=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        if lease_until <= now or self.lease is None:
            raise DomainInvariantError("lease must expire in the future")
        return replace(
            self,
            lease=replace(self.lease, expires_at_utc=lease_until),
            updated_at_utc=now,
        )

    def skip(self, *, now_utc: datetime, reason_code: str) -> ReflectionNodeTask:
        now = self._forward_time(now_utc)
        if self.status not in {
            ReflectionNodeTaskStatus.PENDING,
            ReflectionNodeTaskStatus.RETRY_WAIT,
        }:
            raise DomainInvariantError("only an unclaimed node task can be skipped")
        return replace(
            self,
            status=ReflectionNodeTaskStatus.SKIPPED,
            activated=False,
            last_error_code=require_non_empty(reason_code, "reason_code"),
            available_at_utc=now,
            updated_at_utc=now,
        )

    def cancel(self, *, now_utc: datetime, reason_code: str) -> ReflectionNodeTask:
        if self.is_terminal:
            return self
        now = self._forward_time(now_utc)
        return replace(
            self,
            status=ReflectionNodeTaskStatus.SKIPPED,
            activated=False,
            lease=None,
            lease_generation=self.lease_generation + 1,
            updated_at_utc=now,
            last_error_code=require_non_empty(reason_code, "reason_code"),
        )

    def _artifact_id_for_completion(
        self,
        artifact: ReflectionArtifact | ArtifactRef | UUID,
    ) -> UUID:
        if isinstance(artifact, ReflectionArtifact):
            if artifact.graph_run_id != self.graph_run_id or artifact.node_task_id != self.task_id:
                raise DomainInvariantError("Artifact does not belong to this node task")
            if artifact.attempt != self.attempt_count:
                raise DomainInvariantError("Artifact attempt does not match node task attempt")
            return artifact.artifact_id
        if isinstance(artifact, ArtifactRef):
            return artifact.artifact_id
        if isinstance(artifact, UUID):
            return artifact
        raise DomainInvariantError("completion requires a ReflectionArtifact reference")

    def _require_active_lease(
        self,
        *,
        worker_id: str,
        now: datetime,
        attempt_count: int | None,
        lease_generation: int | None,
    ) -> None:
        if not self.has_valid_lease(
            worker_id=require_non_empty(worker_id, "worker_id"),
            now_utc=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        ):
            raise DomainInvariantError("node task lease is missing, mismatched, or expired")

    def _forward_time(self, value: datetime) -> datetime:
        now = require_utc(value, "now_utc")
        if now < self.updated_at_utc:
            raise DomainInvariantError("node task time cannot move backwards")
        return now


def activate_successor(
    successor: ReflectionNodeTask,
    predecessor: ReflectionNodeTask,
    *,
    now_utc: datetime,
) -> ReflectionNodeTask:
    """Activate a dependent node after its predecessor completed."""

    if successor.graph_run_id != predecessor.graph_run_id:
        raise DomainInvariantError("predecessor and successor use different graph runs")
    if predecessor.node_key not in successor.dependency_keys:
        raise DomainInvariantError("predecessor is not a dependency of the successor")
    if predecessor.status is not ReflectionNodeTaskStatus.COMPLETED:
        raise DomainInvariantError("only a completed predecessor can activate a successor")
    return successor.activate(now_utc=now_utc)
