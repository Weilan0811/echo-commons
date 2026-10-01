from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

import aiosqlite

from echo_commons.domain.errors import DomainInvariantError, require_non_empty, require_utc
from echo_commons.domain.reflection_graph import (
    ArtifactRef,
    ContentFingerprint,
    EvidenceRef,
    GraphSourceRef,
    OutputContractRef,
    ReflectionArtifact,
    ReflectionGraphRun,
    ReflectionGraphRunStatus,
    ReflectionLease,
    ReflectionSourceScope,
    content_fingerprint,
    register_artifact,
)
from echo_commons.domain.reflection_node import ReflectionNodeTask, ReflectionNodeTaskStatus
from echo_commons.domain.reflection_result import (
    GraphReviewRecord,
    GraphReviewStatus,
)
from echo_commons.store.database import Database
from echo_commons.store.repository_support import (
    as_json,
    get_connection,
    parse_time,
    require_write_connection,
    utc_text,
)


def _required_uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise DomainInvariantError(f"{field_name} must contain a UUID")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DomainInvariantError(f"{field_name} must contain a UUID") from exc


def _optional_uuid(value: object, field_name: str) -> UUID | None:
    if value is None:
        return None
    return _required_uuid(value, field_name)


def _required_time(value: object, field_name: str) -> datetime:
    parsed = parse_time(value if isinstance(value, str) else None)
    if parsed is None:
        raise DomainInvariantError(f"{field_name} must contain a timestamp")
    return parsed


def _optional_time(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _required_time(value, field_name)


def _json_value(value: object, field_name: str) -> object:
    try:
        return json.loads(value if isinstance(value, str) else "")
    except json.JSONDecodeError as exc:
        raise DomainInvariantError(f"{field_name} must contain valid JSON") from exc


def _json_list(value: object, field_name: str) -> list[object]:
    parsed = _json_value(value, field_name)
    if not isinstance(parsed, list):
        raise DomainInvariantError(f"{field_name} must contain a JSON list")
    return parsed


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _source_scope_payload(scope: ReflectionSourceScope) -> dict[str, object]:
    sources = sorted(
        (
            {"kind": source.kind, "ref": source.ref, "version": source.version}
            for source in scope.sources
        ),
        key=lambda item: (str(item["kind"]), str(item["ref"]), str(item["version"])),
    )
    return {"sources": sources}


def _source_scope_from_payload(value: object) -> ReflectionSourceScope:
    payload = _json_value(value, "source_scope_json")
    if not isinstance(payload, Mapping):
        raise DomainInvariantError("source_scope_json must contain a JSON object")
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list):
        raise DomainInvariantError("source_scope_json.sources must contain a JSON list")
    sources = tuple(
        GraphSourceRef(
            kind=item["kind"],
            ref=item["ref"],
            version=item["version"],
        )
        for item in raw_sources
        if isinstance(item, Mapping)
    )
    if len(sources) != len(raw_sources):
        raise DomainInvariantError("source_scope_json contains an invalid source")
    return ReflectionSourceScope(sources=sources)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(
        item if isinstance(item, str) else str(item) for item in _json_list(value, field_name)
    )


def _artifact_refs_payload(refs: Sequence[ArtifactRef]) -> list[dict[str, str]]:
    return [
        {"artifact_id": str(ref.artifact_id), "content_fingerprint": ref.content_fingerprint.value}
        for ref in refs
    ]


def _artifact_refs_from_payload(value: object, field_name: str) -> tuple[ArtifactRef, ...]:
    refs: list[ArtifactRef] = []
    for item in _json_list(value, field_name):
        if not isinstance(item, Mapping):
            raise DomainInvariantError(f"{field_name} contains an invalid ArtifactRef")
        refs.append(
            ArtifactRef(
                artifact_id=_required_uuid(item.get("artifact_id"), "artifact_id"),
                content_fingerprint=ContentFingerprint(item.get("content_fingerprint", "")),
            )
        )
    return tuple(refs)


def _evidence_payload(refs: Sequence[EvidenceRef]) -> list[dict[str, str | None]]:
    return [{"kind": ref.kind, "ref": ref.ref, "version": ref.version} for ref in refs]


def _evidence_from_payload(value: object, field_name: str) -> tuple[EvidenceRef, ...]:
    refs: list[EvidenceRef] = []
    for item in _json_list(value, field_name):
        if not isinstance(item, Mapping):
            raise DomainInvariantError(f"{field_name} contains an invalid EvidenceRef")
        refs.append(
            EvidenceRef(
                kind=item.get("kind", ""),
                ref=item.get("ref", ""),
                version=item.get("version"),
            )
        )
    return tuple(refs)


def _check_rowcount(rowcount: int, entity: str) -> None:
    if rowcount != 1:
        raise RuntimeError(f"{entity} persistence precondition failed")


class ReflectionGraphRunRepository:
    """Persist graph identity and aggregate lifecycle state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> ReflectionGraphRun:
        return ReflectionGraphRun(
            graph_run_id=_required_uuid(row["graph_run_id"], "graph_run_id"),
            graph_kind=row["graph_kind"],
            graph_version=row["graph_version"],
            account_id=row["account_id"],
            character_id=row["character_id"],
            context_snapshot_id=row["context_snapshot_id"],
            snapshot_fingerprint=ContentFingerprint(row["snapshot_fingerprint"]),
            source_scope=_source_scope_from_payload(row["source_scope_json"]),
            topology_node_keys=_string_tuple(
                row["topology_node_keys_json"], "topology_node_keys_json"
            ),
            required_node_keys=_string_tuple(
                row["required_node_keys_json"], "required_node_keys_json"
            ),
            registered_node_keys=_string_tuple(
                row["registered_node_keys_json"], "registered_node_keys_json"
            ),
            status=ReflectionGraphRunStatus(row["status"]),
            execution_generation=int(row["execution_generation"]),
            created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
            updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
            started_at_utc=_optional_time(row["started_at_utc"], "started_at_utc"),
            completed_at_utc=_optional_time(row["completed_at_utc"], "completed_at_utc"),
            trace_id=_optional_uuid(row["trace_id"], "trace_id"),
            last_error_code=row["last_error_code"],
        )

    @staticmethod
    def _identity(run: ReflectionGraphRun) -> tuple[object, ...]:
        return (
            _enum_value(run.graph_kind),
            run.graph_version,
            run.account_id,
            run.character_id,
            _source_scope_payload(run.source_scope),
            run.topology_node_keys,
            run.required_node_keys,
        )

    async def _get_row(
        self,
        graph_run_id: UUID,
        connection: aiosqlite.Connection,
    ) -> aiosqlite.Row | None:
        cursor = await connection.execute(
            "SELECT * FROM reflection_graph_runs WHERE graph_run_id = ?",
            (str(graph_run_id),),
        )
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def get(
        self,
        graph_run_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionGraphRun | None:
        conn = get_connection(self.database, connection)
        row = await self._get_row(graph_run_id, conn)
        return self._to_domain(row) if row else None

    async def _get_by_source(
        self,
        run: ReflectionGraphRun,
        connection: aiosqlite.Connection,
    ) -> aiosqlite.Row | None:
        source_payload = _source_scope_payload(run.source_scope)
        source_fingerprint = content_fingerprint(source_payload).value
        cursor = await connection.execute(
            "SELECT * FROM reflection_graph_runs WHERE account_id = ? "
            "AND character_id = ? AND graph_kind = ? AND graph_version = ? "
            "AND source_scope_fingerprint = ?",
            (
                run.account_id,
                run.character_id,
                _enum_value(run.graph_kind),
                run.graph_version,
                source_fingerprint,
            ),
        )
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def create(
        self,
        run: ReflectionGraphRun,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionGraphRun:
        conn = require_write_connection(connection)
        source_payload = _source_scope_payload(run.source_scope)
        await conn.execute(
            """INSERT INTO reflection_graph_runs(
                graph_run_id, account_id, character_id, graph_kind, graph_version,
                context_snapshot_id, snapshot_fingerprint, source_scope_json,
                source_scope_fingerprint, topology_node_keys_json, required_node_keys_json,
                registered_node_keys_json, status, execution_generation,
                created_at_utc, updated_at_utc,
                started_at_utc, completed_at_utc, last_error_code, trace_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(run.graph_run_id),
                run.account_id,
                run.character_id,
                _enum_value(run.graph_kind),
                run.graph_version,
                run.context_snapshot_id,
                run.snapshot_fingerprint.value,
                as_json(source_payload),
                content_fingerprint(source_payload).value,
                as_json(run.topology_node_keys),
                as_json(run.required_node_keys),
                as_json(run.registered_node_keys),
                run.status.value,
                run.execution_generation,
                utc_text(run.created_at_utc),
                utc_text(run.updated_at_utc),
                utc_text(run.started_at_utc) if run.started_at_utc is not None else None,
                utc_text(run.completed_at_utc) if run.completed_at_utc is not None else None,
                run.last_error_code,
                str(run.trace_id) if run.trace_id is not None else None,
            ),
        )
        stored = await self.get(run.graph_run_id, connection=conn)
        if stored is None:
            raise RuntimeError("reflection graph run was not persisted")
        return stored

    async def ensure(
        self,
        run: ReflectionGraphRun,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionGraphRun:
        """Create once by source identity and reject reinterpretation."""

        conn = require_write_connection(connection)
        existing = await self.get(run.graph_run_id, connection=conn)
        if existing is None:
            row = await self._get_by_source(run, conn)
            existing = self._to_domain(row) if row else None
        if existing is not None:
            if self._identity(existing) != self._identity(run):
                raise DomainInvariantError(
                    "reflection graph source identity is bound to different input"
                ) from None
            return existing
        try:
            return await self.create(run, connection=conn)
        except sqlite3.IntegrityError:
            row = await self._get_by_source(run, conn)
            if row is None:
                raise
            existing = self._to_domain(row)
            if self._identity(existing) != self._identity(run):
                raise DomainInvariantError(
                    "reflection graph source identity is bound to different input"
                ) from None
            return existing

    async def save(
        self,
        run: ReflectionGraphRun,
        *,
        expected_updated_at_utc: datetime | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionGraphRun:
        conn = require_write_connection(connection)
        sql = (
            "UPDATE reflection_graph_runs SET registered_node_keys_json = ?, status = ?, "
            "execution_generation = ?, "
            "updated_at_utc = ?, started_at_utc = ?, completed_at_utc = ?, "
            "last_error_code = ? WHERE graph_run_id = ?"
        )
        parameters: tuple[object, ...] = (
            as_json(run.registered_node_keys),
            run.status.value,
            run.execution_generation,
            utc_text(run.updated_at_utc),
            utc_text(run.started_at_utc) if run.started_at_utc is not None else None,
            utc_text(run.completed_at_utc) if run.completed_at_utc is not None else None,
            run.last_error_code,
            str(run.graph_run_id),
        )
        if expected_updated_at_utc is not None:
            sql += " AND updated_at_utc = ?"
            parameters += (utc_text(expected_updated_at_utc),)
        cursor = await conn.execute(sql, parameters)
        _check_rowcount(cursor.rowcount, "reflection graph run")
        stored = await self.get(run.graph_run_id, connection=conn)
        if stored is None:
            raise RuntimeError("reflection graph run disappeared after update")
        return stored

    async def ensure_with_root_tasks(
        self,
        run: ReflectionGraphRun,
        root_tasks: Sequence[ReflectionNodeTask],
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[ReflectionGraphRun, tuple[ReflectionNodeTask, ...]]:
        """Atomically ensure one GraphRun and its root NodeTasks (T1)."""

        conn = require_write_connection(connection)
        if not root_tasks:
            raise DomainInvariantError("T1 requires at least one root NodeTask")
        current = await self.ensure(run, connection=conn)
        node_repository = ReflectionNodeTaskRepository(self.database)
        if current.status in {
            ReflectionGraphRunStatus.RUNNING,
            ReflectionGraphRunStatus.COMPLETED,
        }:
            existing_tasks = await node_repository.list_for_graph(
                current.graph_run_id,
                connection=conn,
            )
            return current, tuple(task for task in existing_tasks if not task.dependency_keys)
        if current.status is ReflectionGraphRunStatus.FAILED:
            current = current.reactivate(now_utc=now_utc)
            await node_repository.reactivate_failed(
                current.graph_run_id,
                now_utc=now_utc,
                connection=conn,
            )
        stored_tasks: list[ReflectionNodeTask] = []
        for task in root_tasks:
            if task.graph_run_id != current.graph_run_id:
                raise DomainInvariantError("root NodeTask belongs to a different GraphRun")
            if task.dependency_keys:
                raise DomainInvariantError("T1 root NodeTask cannot have dependencies")
            stored_tasks.append(await node_repository.ensure(task, connection=conn))
            if task.node_key not in current.registered_node_keys:
                current = current.register_task(task, now_utc=now_utc)
        if current.status is ReflectionGraphRunStatus.PENDING:
            current = current.start(now_utc=now_utc)
        if current != run or stored_tasks:
            current = await self.save(
                current,
                expected_updated_at_utc=(
                    await self.get(current.graph_run_id, connection=conn)
                ).updated_at_utc,
                connection=conn,
            )
        return current, tuple(stored_tasks)


class ReflectionArtifactRepository:
    """Immutable persistence and idempotent lookup for node Artifacts."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> ReflectionArtifact:
        payload = _json_value(row["payload_json"], "payload_json")
        if not isinstance(payload, Mapping):
            raise DomainInvariantError("payload_json must contain an object")
        return ReflectionArtifact(
            artifact_id=_required_uuid(row["artifact_id"], "artifact_id"),
            graph_run_id=_required_uuid(row["graph_run_id"], "graph_run_id"),
            node_task_id=_required_uuid(row["node_task_id"], "node_task_id"),
            invocation_id=_optional_uuid(row["invocation_id"], "invocation_id"),
            attempt=int(row["attempt"]),
            node_input_fingerprint=ContentFingerprint(row["node_input_fingerprint"]),
            output_contract=OutputContractRef(
                kind=row["output_contract_kind"],
                version=row["output_contract_version"],
            ),
            payload=payload,
            evidence_refs=_evidence_from_payload(row["evidence_refs_json"], "evidence_refs_json"),
            content_fingerprint=ContentFingerprint(row["content_fingerprint"]),
            created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
        )

    async def _get_row(
        self,
        artifact_id: UUID,
        connection: aiosqlite.Connection,
    ) -> aiosqlite.Row | None:
        cursor = await connection.execute(
            "SELECT * FROM reflection_artifacts WHERE artifact_id = ?",
            (str(artifact_id),),
        )
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def get(
        self,
        artifact_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionArtifact | None:
        conn = get_connection(self.database, connection)
        row = await self._get_row(artifact_id, conn)
        return self._to_domain(row) if row else None

    async def get_for_task_attempt(
        self,
        node_task_id: UUID,
        attempt: int,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionArtifact | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM reflection_artifacts WHERE node_task_id = ? AND attempt = ?",
            (str(node_task_id), attempt),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def list_for_graph(
        self,
        graph_run_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[ReflectionArtifact, ...]:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM reflection_artifacts WHERE graph_run_id = ? "
            "ORDER BY created_at_utc, artifact_id",
            (str(graph_run_id),),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def _validate_task_ownership(
        self,
        artifact: ReflectionArtifact,
        connection: aiosqlite.Connection,
    ) -> None:
        cursor = await connection.execute(
            "SELECT graph_run_id, attempt_count, node_input_fingerprint, "
            "output_contract_kind, output_contract_version FROM reflection_node_tasks "
            "WHERE node_task_id = ?",
            (str(artifact.node_task_id),),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        if row is None:
            raise DomainInvariantError("Artifact belongs to an unknown graph NodeTask")
        if row["graph_run_id"] != str(artifact.graph_run_id):
            raise DomainInvariantError("Artifact graph run does not match its NodeTask")
        if int(row["attempt_count"]) != artifact.attempt:
            raise DomainInvariantError("Artifact attempt does not match its NodeTask")
        if row["node_input_fingerprint"] != artifact.node_input_fingerprint.value:
            raise DomainInvariantError("Artifact input fingerprint does not match its NodeTask")
        if row["output_contract_kind"] != artifact.output_contract.kind:
            raise DomainInvariantError("Artifact output contract kind does not match its NodeTask")
        if row["output_contract_version"] != artifact.output_contract.version:
            raise DomainInvariantError(
                "Artifact output contract version does not match its NodeTask"
            )

    async def insert(
        self,
        artifact: ReflectionArtifact,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionArtifact:
        conn = require_write_connection(connection)
        await self._validate_task_ownership(artifact, conn)
        audit_payload = {
            "artifact_id": str(artifact.artifact_id),
            "graph_run_id": str(artifact.graph_run_id),
            "node_task_id": str(artifact.node_task_id),
            "attempt": artifact.attempt,
            "invocation_id": str(artifact.invocation_id) if artifact.invocation_id else None,
            "output_contract": artifact.output_contract.schema_id,
            "evidence_count": len(artifact.evidence_refs),
        }
        await conn.execute(
            """INSERT INTO reflection_artifacts(
                artifact_id, graph_run_id, node_task_id, invocation_id, attempt,
                node_input_fingerprint, output_contract_kind, output_contract_version,
                payload_json, content_fingerprint, evidence_refs_json, audit_json,
                created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(artifact.artifact_id),
                str(artifact.graph_run_id),
                str(artifact.node_task_id),
                str(artifact.invocation_id) if artifact.invocation_id else None,
                artifact.attempt,
                artifact.node_input_fingerprint.value,
                artifact.output_contract.kind,
                artifact.output_contract.version,
                as_json(artifact.payload.to_dict()),
                artifact.content_fingerprint.value,
                as_json(_evidence_payload(artifact.evidence_refs)),
                as_json(audit_payload),
                utc_text(artifact.created_at_utc),
            ),
        )
        stored = await self.get(artifact.artifact_id, connection=conn)
        if stored is None:
            raise RuntimeError("reflection Artifact was not persisted")
        return stored

    async def ensure(
        self,
        artifact: ReflectionArtifact,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionArtifact:
        """Register one artifact once by both artifact ID and node attempt."""

        conn = require_write_connection(connection)
        existing = await self.get(artifact.artifact_id, connection=conn)
        if existing is not None:
            return register_artifact(existing, artifact)
        existing = await self.get_for_task_attempt(
            artifact.node_task_id,
            artifact.attempt,
            connection=conn,
        )
        if existing is not None:
            if existing.content_fingerprint == artifact.content_fingerprint:
                return existing
            raise DomainInvariantError("a node attempt already has a different Artifact") from None
        try:
            return await self.insert(artifact, connection=conn)
        except sqlite3.IntegrityError:
            existing = await self.get_for_task_attempt(
                artifact.node_task_id,
                artifact.attempt,
                connection=conn,
            )
            if existing is None:
                raise
            if existing.content_fingerprint == artifact.content_fingerprint:
                return existing
            raise DomainInvariantError("a node attempt already has a different Artifact") from None


@dataclass(frozen=True, slots=True)
class ReflectionNodeCommit:
    """Result of an atomic T3 node completion."""

    task: ReflectionNodeTask
    artifact: ReflectionArtifact
    activated_successors: tuple[ReflectionNodeTask, ...]


class ReflectionNodeTaskRepository:
    """Canonical graph NodeTask persistence, leases, and T2/T3 boundaries."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> ReflectionNodeTask:
        lease = None
        if row["lease_owner"] is not None:
            lease = ReflectionLease(
                owner=row["lease_owner"],
                attempt=int(row["attempt_count"]),
                generation=int(row["lease_generation"]),
                expires_at_utc=_required_time(row["lease_until_utc"], "lease_until_utc"),
            )
        return ReflectionNodeTask(
            task_id=_required_uuid(row["node_task_id"], "node_task_id"),
            graph_run_id=_required_uuid(row["graph_run_id"], "graph_run_id"),
            node_key=row["node_key"],
            node_kind=row["node_kind"],
            dependency_keys=_string_tuple(row["dependency_keys_json"], "dependency_keys_json"),
            node_input_fingerprint=ContentFingerprint(row["node_input_fingerprint"]),
            output_contract=OutputContractRef(
                kind=row["output_contract_kind"],
                version=row["output_contract_version"],
            ),
            available_at_utc=_required_time(row["available_at_utc"], "available_at_utc"),
            created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
            updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
            status=ReflectionNodeTaskStatus(row["status"]),
            activated=bool(row["activated"]),
            input_artifact_refs=_artifact_refs_from_payload(
                row["input_artifact_refs_json"], "input_artifact_refs_json"
            ),
            attempt_count=int(row["attempt_count"]),
            lease_generation=int(row["lease_generation"]),
            lease=lease,
            artifact_id=_optional_uuid(row["artifact_id"], "artifact_id"),
            last_error_code=row["last_error_code"],
        )

    @staticmethod
    def _identity(task: ReflectionNodeTask) -> tuple[object, ...]:
        return (
            str(task.graph_run_id),
            task.node_key,
            _enum_value(task.node_kind),
            task.dependency_keys,
            task.node_input_fingerprint.value,
            task.output_contract.schema_id,
            task.activated,
            tuple(
                (str(ref.artifact_id), ref.content_fingerprint.value)
                for ref in task.input_artifact_refs
            ),
        )

    @staticmethod
    def _idempotency_key(task: ReflectionNodeTask) -> str:
        return f"reflection-node:{task.graph_run_id}:{task.node_key}"

    async def _get_row(
        self,
        task_id: UUID,
        connection: aiosqlite.Connection,
    ) -> aiosqlite.Row | None:
        cursor = await connection.execute(
            "SELECT * FROM reflection_node_tasks WHERE node_task_id = ?",
            (str(task_id),),
        )
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def get(
        self,
        task_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionNodeTask | None:
        conn = get_connection(self.database, connection)
        row = await self._get_row(task_id, conn)
        return self._to_domain(row) if row else None

    async def get_for_graph_node(
        self,
        graph_run_id: UUID,
        node_key: str,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionNodeTask | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM reflection_node_tasks WHERE graph_run_id = ? AND node_key = ?",
            (str(graph_run_id), require_non_empty(node_key, "node_key")),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def list_for_graph(
        self,
        graph_run_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[ReflectionNodeTask, ...]:
        """Return graph NodeTasks in deterministic creation order."""

        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM reflection_node_tasks WHERE graph_run_id = ? "
            "ORDER BY created_at_utc, node_task_id",
            (str(graph_run_id),),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(self._to_domain(row) for row in rows)

    async def create(
        self,
        task: ReflectionNodeTask,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionNodeTask:
        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT INTO reflection_node_tasks(
                node_task_id, status, attempt_count, lease_generation,
                available_at_utc, lease_owner, lease_until_utc, last_error_code,
                created_at_utc, updated_at_utc, graph_run_id, node_key, node_kind,
                dependency_keys_json, activated, node_input_fingerprint,
                input_artifact_refs_json, output_contract_kind, output_contract_version,
                artifact_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(task.task_id),
                task.status.value,
                task.attempt_count,
                task.lease_generation,
                utc_text(task.available_at_utc),
                task.lease_owner,
                utc_text(task.lease_until_utc) if task.lease_until_utc else None,
                task.last_error_code,
                utc_text(task.created_at_utc),
                utc_text(task.updated_at_utc),
                str(task.graph_run_id),
                task.node_key,
                _enum_value(task.node_kind),
                as_json(task.dependency_keys),
                int(task.activated),
                task.node_input_fingerprint.value,
                as_json(_artifact_refs_payload(task.input_artifact_refs)),
                task.output_contract.kind,
                task.output_contract.version,
                str(task.artifact_id) if task.artifact_id else None,
            ),
        )
        stored = await self.get(task.task_id, connection=conn)
        if stored is None:
            raise RuntimeError("reflection NodeTask was not persisted")
        return stored

    async def ensure(
        self,
        task: ReflectionNodeTask,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionNodeTask:
        conn = require_write_connection(connection)
        existing = await self.get_for_graph_node(task.graph_run_id, task.node_key, connection=conn)
        if existing is None:
            existing = await self.get(task.task_id, connection=conn)
        if existing is not None:
            if self._identity(existing) != self._identity(task):
                raise DomainInvariantError("graph NodeTask identity is bound to different input")
            return existing
        try:
            return await self.create(task, connection=conn)
        except sqlite3.IntegrityError:
            existing = await self.get_for_graph_node(
                task.graph_run_id,
                task.node_key,
                connection=conn,
            )
            if existing is None:
                raise
            if self._identity(existing) != self._identity(task):
                raise DomainInvariantError(
                    "graph NodeTask identity is bound to different input"
                ) from None
            return existing

    async def reactivate_failed(
        self,
        graph_run_id: UUID,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> int:
        """Make failed nodes runnable again for a new source execution generation."""

        conn = require_write_connection(connection)
        now = require_utc(now_utc, "now_utc")
        cursor = await conn.execute(
            "UPDATE reflection_node_tasks SET status = 'pending', activated = 1, "
            "available_at_utc = ?, lease_owner = NULL, lease_until_utc = NULL, "
            "last_error_code = NULL, updated_at_utc = ? "
            "WHERE graph_run_id = ? AND status = 'failed'",
            (utc_text(now), utc_text(now), str(graph_run_id)),
        )
        return cursor.rowcount

    async def _save(
        self,
        task: ReflectionNodeTask,
        *,
        expected_updated_at_utc: datetime | None,
        connection: aiosqlite.Connection,
        expected_lease: tuple[str, int, int] | None = None,
    ) -> ReflectionNodeTask:
        sql = (
            "UPDATE reflection_node_tasks SET status = ?, attempt_count = ?, lease_generation = ?, "
            "available_at_utc = ?, lease_owner = ?, lease_until_utc = ?, last_error_code = ?, "
            "activated = ?, artifact_id = ?, node_input_fingerprint = ?, "
            "input_artifact_refs_json = ?, updated_at_utc = ? "
            "WHERE node_task_id = ?"
        )
        parameters: tuple[object, ...] = (
            task.status.value,
            task.attempt_count,
            task.lease_generation,
            utc_text(task.available_at_utc),
            task.lease_owner,
            utc_text(task.lease_until_utc) if task.lease_until_utc else None,
            task.last_error_code,
            int(task.activated),
            str(task.artifact_id) if task.artifact_id else None,
            task.node_input_fingerprint.value,
            as_json(_artifact_refs_payload(task.input_artifact_refs)),
            utc_text(task.updated_at_utc),
            str(task.task_id),
        )
        if expected_updated_at_utc is not None:
            sql += " AND updated_at_utc = ?"
            parameters += (utc_text(expected_updated_at_utc),)
        if expected_lease is not None:
            sql += " AND status = 'processing' AND lease_owner = ? "
            sql += "AND attempt_count = ? AND lease_generation = ?"
            parameters += expected_lease
        cursor = await connection.execute(sql, parameters)
        _check_rowcount(cursor.rowcount, "reflection NodeTask")
        stored = await self.get(task.task_id, connection=connection)
        if stored is None:
            raise RuntimeError("reflection NodeTask disappeared after update")
        return stored

    async def bind_input_artifacts(
        self,
        task_id: UUID,
        *,
        input_artifact_refs: Sequence[ArtifactRef],
        node_input_fingerprint: ContentFingerprint | str,
        now_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionNodeTask:
        """Persist the immutable predecessor input boundary for a task."""

        conn = require_write_connection(connection)
        current = await self.get(task_id, connection=conn)
        if current is None:
            raise LookupError("reflection_node_task_not_found")
        updated = current.bind_input_artifacts(
            input_artifact_refs=input_artifact_refs,
            node_input_fingerprint=node_input_fingerprint,
            now_utc=now_utc,
        )
        return await self._save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
        )

    async def recover_expired(
        self,
        now_utc: datetime,
        *,
        graph_run_id: UUID | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> int:
        conn = require_write_connection(connection)
        now = require_utc(now_utc, "now_utc")
        sql = (
            "SELECT * FROM reflection_node_tasks "
            "WHERE status = 'processing' AND lease_until_utc IS NOT NULL AND lease_until_utc <= ?"
        )
        parameters: tuple[object, ...] = (utc_text(now),)
        if graph_run_id is not None:
            sql += " AND graph_run_id = ?"
            parameters += (str(graph_run_id),)
        cursor = await conn.execute(sql, parameters)
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        recovered = 0
        for row in rows:
            current = self._to_domain(row)
            updated = current.recover_expired(now_utc=now)
            await self._save(
                updated,
                expected_updated_at_utc=current.updated_at_utc,
                connection=conn,
            )
            recovered += 1
        return recovered

    async def claim_next(
        self,
        *,
        graph_run_id: UUID,
        worker_id: str,
        now_utc: datetime,
        lease_seconds: float,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionNodeTask | None:
        if lease_seconds <= 0:
            raise DomainInvariantError("lease_seconds must be positive")
        if connection is None:
            async with self.database.transaction(immediate=True) as conn:
                return await self.claim_next(
                    graph_run_id=graph_run_id,
                    worker_id=worker_id,
                    now_utc=now_utc,
                    lease_seconds=lease_seconds,
                    connection=conn,
                )
        conn = require_write_connection(connection)
        now = require_utc(now_utc, "now_utc")
        run_row = await conn.execute(
            "SELECT status FROM reflection_graph_runs WHERE graph_run_id = ?",
            (str(graph_run_id),),
        )
        try:
            run_status = await run_row.fetchone()
        finally:
            await run_row.close()
        if run_status is None or run_status["status"] != "running":
            return None
        await self.recover_expired(now, graph_run_id=graph_run_id, connection=conn)
        resolved_cursor = await conn.execute(
            "SELECT node_key FROM reflection_node_tasks WHERE graph_run_id = ? "
            "AND status IN ('completed', 'skipped', 'failed')",
            (str(graph_run_id),),
        )
        try:
            resolved_rows = await resolved_cursor.fetchall()
        finally:
            await resolved_cursor.close()
        resolved_keys = {row["node_key"] for row in resolved_rows}
        cursor = await conn.execute(
            "SELECT * FROM reflection_node_tasks WHERE graph_run_id = ? "
            "AND activated = 1 AND status IN ('pending', 'retry_wait') "
            "AND available_at_utc <= ? "
            "ORDER BY available_at_utc, created_at_utc, node_task_id",
            (str(graph_run_id), utc_text(now)),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        for row in rows:
            current = self._to_domain(row)
            if not current.is_claimable(
                completed_node_keys=(),
                resolved_node_keys=resolved_keys,
            ):
                continue
            claimed = current.claim(
                worker_id=worker_id,
                now_utc=now,
                lease_until_utc=now + timedelta(seconds=lease_seconds),
                completed_node_keys=(),
                resolved_node_keys=resolved_keys,
            )
            return await self._save(
                claimed,
                expected_updated_at_utc=current.updated_at_utc,
                connection=conn,
            )
        return None

    async def claim_next_ready(
        self,
        *,
        account_id: str,
        character_id: str | None,
        worker_id: str,
        now_utc: datetime,
        lease_seconds: float,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionNodeTask | None:
        """Claim the next runnable node across active graph runs.

        The query only chooses graph identities.  The existing per-graph
        claim method remains the single owner of dependency and lease rules.
        """

        if connection is None:
            async with self.database.transaction(immediate=True) as conn:
                return await self.claim_next_ready(
                    account_id=account_id,
                    character_id=character_id,
                    worker_id=worker_id,
                    now_utc=now_utc,
                    lease_seconds=lease_seconds,
                    connection=conn,
                )
        conn = require_write_connection(connection)
        account = require_non_empty(account_id, "account_id")
        parameters: list[object] = [account]
        sql = (
            "SELECT graph_run_id FROM reflection_graph_runs "
            "WHERE account_id = ? AND status = 'running'"
        )
        if character_id is not None:
            sql += " AND character_id = ?"
            parameters.append(require_non_empty(character_id, "character_id"))
        sql += " ORDER BY updated_at_utc, created_at_utc, graph_run_id"
        cursor = await conn.execute(sql, tuple(parameters))
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        for row in rows:
            task = await self.claim_next(
                graph_run_id=_required_uuid(row["graph_run_id"], "graph_run_id"),
                worker_id=worker_id,
                now_utc=now_utc,
                lease_seconds=lease_seconds,
                connection=conn,
            )
            if task is not None:
                return task
        return None

    async def renew_lease(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        now_utc: datetime,
        lease_seconds: float,
        attempt_count: int,
        lease_generation: int,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionNodeTask | None:
        if lease_seconds <= 0:
            raise DomainInvariantError("lease_seconds must be positive")
        if connection is None:
            async with self.database.transaction(immediate=True) as conn:
                return await self.renew_lease(
                    task_id,
                    worker_id=worker_id,
                    now_utc=now_utc,
                    lease_seconds=lease_seconds,
                    attempt_count=attempt_count,
                    lease_generation=lease_generation,
                    connection=conn,
                )
        conn = require_write_connection(connection)
        now = require_utc(now_utc, "now_utc")
        current = await self.get(task_id, connection=conn)
        if current is None or not current.has_valid_lease(
            worker_id=worker_id,
            now_utc=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        ):
            return None
        renewed = current.renew_lease(
            worker_id=worker_id,
            now_utc=now,
            lease_until_utc=now + timedelta(seconds=lease_seconds),
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        return await self._save(
            renewed,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
            expected_lease=(worker_id, attempt_count, lease_generation),
        )

    async def complete_with_artifact(
        self,
        task_id: UUID,
        artifact: ReflectionArtifact,
        *,
        worker_id: str,
        now_utc: datetime,
        attempt_count: int,
        lease_generation: int,
        activate_successors: bool = True,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionNodeCommit:
        """Atomically execute T3 for a successful node attempt."""

        conn = require_write_connection(connection)
        now = require_utc(now_utc, "now_utc")
        current = await self.get(task_id, connection=conn)
        if current is None:
            raise LookupError("reflection_node_task_not_found")
        if (
            artifact.node_task_id != current.task_id
            or artifact.graph_run_id != current.graph_run_id
        ):
            raise DomainInvariantError("Artifact does not belong to the claimed NodeTask")
        if not current.has_valid_lease(
            worker_id=worker_id,
            now_utc=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        ):
            raise DomainInvariantError("NodeTask lease is missing, mismatched, or expired")
        persisted_artifact = await ReflectionArtifactRepository(self.database).ensure(
            artifact,
            connection=conn,
        )
        completed = current.complete(
            worker_id=worker_id,
            now_utc=now,
            artifact=persisted_artifact,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        saved = await self._save(
            completed,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
            expected_lease=(worker_id, attempt_count, lease_generation),
        )
        activated: list[ReflectionNodeTask] = []
        if activate_successors:
            cursor = await conn.execute(
                "SELECT * FROM reflection_node_tasks WHERE graph_run_id = ? "
                "AND activated = 0 AND status IN ('pending', 'retry_wait')",
                (str(saved.graph_run_id),),
            )
            try:
                successor_rows = await cursor.fetchall()
            finally:
                await cursor.close()
            for row in successor_rows:
                successor = self._to_domain(row)
                if saved.node_key not in successor.dependency_keys:
                    continue
                updated_successor = successor.activate(now_utc=now)
                activated.append(
                    await self._save(
                        updated_successor,
                        expected_updated_at_utc=successor.updated_at_utc,
                        connection=conn,
                    )
                )
        return ReflectionNodeCommit(
            task=saved,
            artifact=persisted_artifact,
            activated_successors=tuple(activated),
        )

    async def retry_or_fail(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        now_utc: datetime,
        available_at_utc: datetime,
        error_code: str,
        max_attempts: int,
        attempt_count: int,
        lease_generation: int,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionNodeTask:
        conn = require_write_connection(connection)
        current = await self.get(task_id, connection=conn)
        if current is None:
            raise LookupError("reflection_node_task_not_found")
        updated = current.retry_or_fail(
            worker_id=worker_id,
            now_utc=now_utc,
            available_at_utc=available_at_utc,
            error_code=error_code,
            max_attempts=max_attempts,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        return await self._save(
            updated,
            expected_updated_at_utc=current.updated_at_utc,
            connection=conn,
            expected_lease=(worker_id, attempt_count, lease_generation),
        )


class GraphReviewRepository:
    """Persist one review record for each graph aggregate."""

    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _to_domain(row: aiosqlite.Row) -> GraphReviewRecord:
        return GraphReviewRecord(
            result_id=_required_uuid(row["result_id"], "result_id"),
            graph_run_id=_required_uuid(row["graph_run_id"], "graph_run_id"),
            aggregate_fingerprint=row["aggregate_fingerprint"],
            payload_json=row["payload_json"],
            created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
            status=GraphReviewStatus(row["status"]),
            decision_code=row["decision_code"],
            decided_at_utc=_optional_time(row["decided_at_utc"], "decided_at_utc"),
        )

    async def get(
        self,
        result_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> GraphReviewRecord | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM reflection_graph_results WHERE result_id = ?",
            (str(result_id),),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def get_for_graph(
        self,
        graph_run_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> GraphReviewRecord | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM reflection_graph_results WHERE graph_run_id = ?",
            (str(graph_run_id),),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._to_domain(row) if row else None

    async def ensure(
        self,
        result: GraphReviewRecord,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> GraphReviewRecord:
        conn = require_write_connection(connection)
        existing = await self.get(result.result_id, connection=conn)
        if existing is not None:
            if existing != result:
                raise DomainInvariantError("graph review identity is bound to different data")
            return existing
        existing = await self.get_for_graph(result.graph_run_id, connection=conn)
        if existing is not None:
            if existing.payload_json != result.payload_json:
                raise DomainInvariantError("graph run already has a different review record")
            return existing
        await conn.execute(
            "INSERT INTO reflection_graph_results("
            "result_id, graph_run_id, aggregate_fingerprint, payload_json, status, "
            "decision_code, created_at_utc, decided_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(result.result_id),
                str(result.graph_run_id),
                result.aggregate_fingerprint,
                result.payload_json,
                result.status.value,
                result.decision_code,
                utc_text(result.created_at_utc),
                utc_text(result.decided_at_utc) if result.decided_at_utc else None,
            ),
        )
        stored = await self.get(result.result_id, connection=conn)
        if stored is None:
            raise RuntimeError("graph review record was not persisted")
        return stored

    async def save_decision(
        self,
        result: GraphReviewRecord,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> GraphReviewRecord:
        conn = require_write_connection(connection)
        cursor = await conn.execute(
            "UPDATE reflection_graph_results SET status = ?, decision_code = ?, decided_at_utc = ? "
            "WHERE result_id = ? AND status = 'pending'",
            (
                result.status.value,
                result.decision_code,
                utc_text(result.decided_at_utc) if result.decided_at_utc else None,
                str(result.result_id),
            ),
        )
        _check_rowcount(cursor.rowcount, "graph review record")
        stored = await self.get(result.result_id, connection=conn)
        if stored is None:
            raise RuntimeError("graph review record disappeared after decision")
        return stored


__all__ = [
    "ReflectionArtifactRepository",
    "GraphReviewRepository",
    "ReflectionGraphRunRepository",
    "ReflectionNodeCommit",
    "ReflectionNodeTaskRepository",
]
