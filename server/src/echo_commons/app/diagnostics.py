from typing import Annotated

from fastapi import APIRouter, Depends

from echo_commons.app.composition import Application
from echo_commons.app.http import application_for

router = APIRouter(prefix="/internal", tags=["diagnostics"])
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.get("/characters/{character_id}/tasks/{task_id}/context")
def task_context(
    character_id: str,
    task_id: str,
    community_id: str,
    application: ApplicationDependency,
):
    return application.conversation_diagnostics.context(community_id, character_id, task_id)


@router.get("/reflection/runs/{graph_run_id}")
def reflection_run(
    graph_run_id: str,
    community_id: str,
    character_id: str,
    application: ApplicationDependency,
):
    return application.reflection_view.get(community_id, character_id, graph_run_id)


@router.get("/traces/{correlation_id}")
def traces(correlation_id: str, application: ApplicationDependency):
    return {
        "correlation_id": correlation_id,
        "traces": application.trace_query.read(correlation_id),
    }
