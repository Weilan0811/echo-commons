"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from echo_server import __version__
from echo_server.agents.contracts import RunnableAgent
from echo_server.agents.factory import build_default_character_agent
from echo_server.agents.harness import ToolRegistration
from echo_server.api.router import api_router
from echo_server.config import Settings, load_settings
from echo_server.observability.logging import configure_logging, get_logger, log_event
from echo_server.runtime.application_runtime import (
    ApplicationRuntime,
    DatabaseUnavailableError,
    IdempotencyConflictError,
    InvalidCursorError,
    UnknownConversationError,
    UnsupportedCapabilityError,
)
from echo_server.runtime.conversation_worker import ConversationWorker
from echo_server.runtime.memory import MemorySearchTool, memory_search_progress_keys
from echo_server.runtime.reflection import ReflectionWorker
from echo_server.services.context import ContextSnapshotSource, RepositoryContextSource
from echo_server.services.identity import load_identity_catalog
from echo_server.services.memory import MemorySearchService
from echo_server.services.model_gateway import ModelRegistry
from echo_server.store.database import Database


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Own database and the single worker task for the entire app lifetime."""

    runtime: ApplicationRuntime = application.state.runtime
    configure_logging(runtime.settings)
    logger = get_logger("lifecycle")
    worker: ConversationWorker | None = None
    reflection_worker: ReflectionWorker | None = None
    application.state.lifecycle_status = "starting"
    application.state.migration_status = "pending"
    application.state.lifecycle_failure_code = None
    application.state.ready = False
    log_event(
        logger,
        logging.INFO,
        "service.starting",
        server_version=__version__,
    )
    try:
        await runtime.start()
        application.state.migration_status = "ok"
        worker = ConversationWorker(runtime)
        application.state.worker = worker
        reflection_worker = ReflectionWorker(runtime.reflection_module)
        application.state.reflection_worker = reflection_worker
        if runtime.settings.worker_enabled:
            await worker.start()
            await reflection_worker.start()
        application.state.ready = True
        application.state.lifecycle_status = "started"
        log_event(logger, logging.INFO, "service.ready", worker_id=runtime.worker_id)
        yield
    except Exception as exc:
        application.state.lifecycle_status = "failed"
        if application.state.migration_status == "pending":
            application.state.migration_status = "failed"
        application.state.lifecycle_failure_code = (
            getattr(exc, "code", None) or exc.__class__.__name__.lower()
        )
        log_event(
            logger,
            logging.ERROR,
            "service.lifecycle_failed",
            error_code=getattr(exc, "code", None) or exc.__class__.__name__.lower(),
            error_type=exc.__class__.__name__,
        )
        raise
    finally:
        application.state.ready = False
        if worker is not None:
            await worker.stop()
        if reflection_worker is not None:
            await reflection_worker.stop()
        await runtime.stop()
        if application.state.lifecycle_status != "failed":
            application.state.lifecycle_status = "stopped"
        log_event(logger, logging.INFO, "service.stopped")


def create_app(
    settings: Settings | None = None,
    agent: RunnableAgent | None = None,
    *,
    # test: 测试运行器可传入来源工厂；这里转交给 Runtime，启动时才创建实际来源。
    context_source_factory: (
        Callable[[RepositoryContextSource], ContextSnapshotSource] | None
    ) = None,  # ------仅测试用模块-----
    # test: 每个隔离运行实例可选择自己的模型注册表，不改动正式配置文件。
    model_registry: ModelRegistry | None = None,  # ------仅测试用模块-----
) -> FastAPI:
    resolved_settings = settings or load_settings()
    database = Database(resolved_settings.database_path)
    memory_search = MemorySearchService(database)
    memory_search_tool = MemorySearchTool(
        memory_search,
        account_id=resolved_settings.account_id,
    )
    resolved_agent = agent or build_default_character_agent(
        resolved_settings,
        tools=(
            ToolRegistration(
                tool=memory_search_tool,
                progress_extractor=memory_search_progress_keys,
                no_progress_limit=2,
            ),
        ),
        model_registry=model_registry,
    )
    identity_catalog = load_identity_catalog(resolved_settings.identity_root)
    application = FastAPI(
        title="Echo Agent Service",
        version=__version__,
        docs_url="/docs" if resolved_settings.environment == "development" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.identity_catalog = identity_catalog
    application.state.runtime = ApplicationRuntime(
        database,
        resolved_agent,
        resolved_settings,
        identity_catalog=identity_catalog,
        memory_search=memory_search,
        context_source_factory=context_source_factory,
    )
    application.state.ready = False
    application.state.lifecycle_status = "starting"
    application.state.migration_status = "pending"
    application.state.lifecycle_failure_code = None
    application.state.worker = None
    application.state.reflection_worker = None
    application.include_router(api_router)
    if resolved_settings.environment == "development":
        application.add_middleware(
            CORSMiddleware,
            allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )

    @application.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(_: Request, exc: IdempotencyConflictError) -> JSONResponse:
        return _error_response(
            exc.code, "The clientMsgId was already used with different content.", 409
        )

    @application.exception_handler(UnknownConversationError)
    async def unknown_conversation(_: Request, exc: UnknownConversationError) -> JSONResponse:
        return _error_response("invalid_request", "The request is invalid.", 422)

    @application.exception_handler(UnsupportedCapabilityError)
    async def unsupported_request(_: Request, exc: UnsupportedCapabilityError) -> JSONResponse:
        return _error_response(exc.code, "Images are not supported.", 422)

    @application.exception_handler(InvalidCursorError)
    async def invalid_request(_: Request, exc: Exception) -> JSONResponse:
        return _error_response("invalid_request", "The request is invalid.", 422)

    @application.exception_handler(DatabaseUnavailableError)
    async def database_unavailable(_: Request, exc: DatabaseUnavailableError) -> JSONResponse:
        return _error_response(exc.code, "The service could not persist or read data.", 503)

    @application.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return _error_response("invalid_request", "The request is invalid.", 422)

    return application


def _error_response(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "traceId": str(uuid4())},
    )


app = create_app()
