from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from echo_commons.app.composition import Application
from echo_commons.app.http import application_for
from echo_commons.infrastructure.database.errors import StorageError

router = APIRouter(prefix="/health", tags=["health"])
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.get("/ready")
def ready(application: ApplicationDependency):
    database_ready = False
    try:
        with application.database.read() as connection:
            migration = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
            database_ready = migration is not None
    except StorageError:
        database_ready = False
    workers = {name: state.status for name, state in application.supervisor.states.items()}
    workers_ready = (
        all(status == "running" for status in workers.values())
        if application.settings.worker_enabled
        else True
    )
    is_ready = application.started and database_ready and workers_ready
    return JSONResponse(
        status_code=200 if is_ready else 503,
        content={
            "status": "ready" if is_ready else "unready",
            "database": database_ready,
            "workers_enabled": application.settings.worker_enabled,
            "workers": workers,
        },
    )
