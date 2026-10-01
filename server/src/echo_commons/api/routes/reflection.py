from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from echo_commons.api.dependencies import get_runtime
from echo_commons.api.schemas.reflection import ReflectionRunViewResponse
from echo_commons.runtime.application_runtime import ApplicationRuntime

router = APIRouter(prefix="/internal/reflection", tags=["reflection-diagnostics"])


@router.get(
    "/runs/{graph_run_id}",
    response_model=ReflectionRunViewResponse,
)
async def get_reflection_run(
    graph_run_id: UUID,
    runtime: ApplicationRuntime = Depends(get_runtime),  # noqa: B008
) -> ReflectionRunViewResponse:
    view = await runtime.reflection_run_view.get(graph_run_id)
    if view is None:
        raise HTTPException(status_code=404, detail="reflection graph run not found")
    return ReflectionRunViewResponse.model_validate(view.to_payload())


__all__ = ["router"]
