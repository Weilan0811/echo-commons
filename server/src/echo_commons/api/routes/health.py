"""Service health endpoint used by the launcher and settings screen."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from echo_server import __version__

router = APIRouter(tags=["service"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ReadinessResponse(BaseModel):
    """Detailed lifecycle state used by process supervisors and diagnostics."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["ready", "not_ready", "disabled"]
    service: str
    version: str
    runtime_status: Literal["starting", "started", "stopped", "failed"] = Field(
        alias="runtimeStatus"
    )
    migration_status: Literal["pending", "ok", "failed"] = Field(alias="migrationStatus")
    worker_status: Literal["not_started", "running", "disabled", "failed", "stopped"] = Field(
        alias="workerStatus"
    )
    worker_enabled: bool = Field(alias="workerEnabled")
    last_worker_loop_at: datetime | None = Field(default=None, alias="lastWorkerLoopAt")
    failure_code: str | None = Field(default=None, alias="failureCode")


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Return the backwards-compatible service probe."""

    worker = getattr(request.app.state, "worker", None)
    reflection_worker = getattr(request.app.state, "reflection_worker", None)
    failures = tuple(
        worker_item.failure
        for worker_item in (worker, reflection_worker)
        if worker_item is not None and worker_item.failure is not None
    )
    status = "not_ready" if failures else "ok"
    return HealthResponse(status=status, service="echo-agent-service", version=__version__)


@router.get("/health/live", response_model=HealthResponse)
async def get_liveness() -> HealthResponse:
    """Report that the HTTP process can serve requests."""

    return HealthResponse(status="ok", service="echo-agent-service", version=__version__)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Service is not ready"}},
)
async def get_readiness(request: Request) -> ReadinessResponse | JSONResponse:
    """Report whether Runtime and its configured background workers are usable."""

    response = _readiness_response(request)
    if response.status == "ready":
        return response
    return JSONResponse(status_code=503, content=response.model_dump(mode="json", by_alias=True))


def _readiness_response(request: Request) -> ReadinessResponse:
    application = request.app
    runtime = getattr(application.state, "runtime", None)
    settings = getattr(application.state, "settings", None)
    worker = getattr(application.state, "worker", None)
    reflection_worker = getattr(application.state, "reflection_worker", None)

    lifecycle_status = getattr(application.state, "lifecycle_status", "starting")
    migration_status = getattr(application.state, "migration_status", "pending")
    runtime_started = runtime is not None and runtime.started
    if runtime_started:
        runtime_status = "started"
        if migration_status == "pending":
            migration_status = "ok"
    elif lifecycle_status == "failed":
        runtime_status = "failed"
    elif lifecycle_status == "stopped":
        runtime_status = "stopped"
    else:
        runtime_status = "starting"

    worker_enabled = bool(getattr(settings, "worker_enabled", False))
    workers = tuple(
        worker_item for worker_item in (worker, reflection_worker) if worker_item is not None
    )
    if not worker_enabled:
        worker_status = "disabled"
    elif not workers:
        worker_status = "not_started"
    elif any(worker_item.failure is not None for worker_item in workers):
        worker_status = "failed"
    elif all(
        worker_item.task is not None and not worker_item.task.done() for worker_item in workers
    ):
        worker_status = "running"
    elif lifecycle_status == "stopped":
        worker_status = "stopped"
    else:
        worker_status = "not_started"

    failure_code = getattr(application.state, "lifecycle_failure_code", None)
    failures = tuple(
        worker_item.failure for worker_item in workers if worker_item.failure is not None
    )
    if failures:
        failure = failures[0]
        failure_code = getattr(failure, "code", None) or failure.__class__.__name__.lower()

    ready = (
        bool(getattr(application.state, "ready", False))
        and runtime_status == "started"
        and migration_status == "ok"
        and worker_status == "running"
    )
    status = "ready" if ready else "disabled" if worker_status == "disabled" else "not_ready"

    return ReadinessResponse(
        status=status,
        service="echo-agent-service",
        version=__version__,
        runtimeStatus=runtime_status,
        migrationStatus=migration_status,
        workerStatus=worker_status,
        workerEnabled=worker_enabled,
        lastWorkerLoopAt=(worker.last_successful_loop_at if worker is not None else None),
        failureCode=failure_code,
    )
