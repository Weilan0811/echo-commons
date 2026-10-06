import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from echo_commons.app.composition import Application, assemble
from echo_commons.app.settings import Settings
from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.infrastructure.observability.logging import close_logging, configure_logging


@asynccontextmanager
async def application_lifecycle(settings: Settings) -> AsyncIterator[Application]:
    application = assemble(settings)
    configure_logging(settings)
    try:
        await asyncio.to_thread(initialize, application.database)
        await application.queue.recover(utc_now())
        await application.reflection_queue.recover(utc_now())
        application.started = True
        if settings.worker_enabled:
            await application.supervisor.start()
        yield application
    finally:
        application.started = False
        await application.supervisor.close()
        if application.embeddings is not None:
            await application.embeddings.close()
        await application.gateway.close()
        close_logging()


def lifespan_for(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with application_lifecycle(settings) as application:
            app.state.application = application
            yield

    return lifespan
