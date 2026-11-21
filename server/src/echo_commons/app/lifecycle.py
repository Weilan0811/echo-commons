import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from fastapi import FastAPI

from echo_commons.app.composition import Application, assemble
from echo_commons.app.settings import Settings
from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.infrastructure.observability.logging import close_logging, configure_logging


@asynccontextmanager
async def application_lifecycle(
    settings: Settings, *, prompt_examples: Mapping[str, str] | None = None
) -> AsyncIterator[Application]:
    application = assemble(settings, prompt_examples=prompt_examples)
    configure_logging(settings)
    try:
        await asyncio.to_thread(initialize, application.database)
        application.activity_lifecycle.attach()
        await asyncio.to_thread(application.assets.recover)
        application.image_generations.recover()
        await application.realtime.start()
        await application.queue.recover(utc_now())
        await application.activity_queue.recover(utc_now())
        await application.reflection_queue.recover(utc_now())
        application.started = True
        if settings.worker_enabled:
            await application.supervisor.start()
        yield application
    finally:
        application.started = False
        await application.supervisor.close()
        await application.rapfi.close()
        await application.realtime.close()
        if application.embeddings is not None:
            await application.embeddings.close()
        if application.decisions is not None:
            await application.decisions.close()
        await application.planner.judgments.close()
        await application.image_generations.gateway.close()
        await application.gateway.close()
        close_logging()


def lifespan_for(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with application_lifecycle(settings) as application:
            app.state.application = application
            yield

    return lifespan
