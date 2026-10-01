import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.main import create_app


@pytest.mark.asyncio
async def test_health_reports_service_identity() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "echo-agent-service",
        "version": "0.1.0",
    }


@pytest.mark.asyncio
async def test_liveness_is_ok_before_runtime_lifecycle_starts(tmp_path) -> None:
    app = create_app(
        Settings(database_path=str(tmp_path / "echo.sqlite3")),
        StubCharacterAgent(),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "echo-agent-service",
        "version": "0.1.0",
    }


@pytest.mark.asyncio
async def test_readiness_reports_starting_before_lifespan(tmp_path) -> None:
    app = create_app(
        Settings(database_path=str(tmp_path / "echo.sqlite3")),
        StubCharacterAgent(),
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["runtimeStatus"] == "starting"
    assert body["migrationStatus"] == "pending"
    assert body["workerStatus"] == "not_started"
    assert body["workerEnabled"] is True


@pytest.mark.asyncio
async def test_readiness_reports_running_worker_and_last_success(tmp_path) -> None:
    app = create_app(
        Settings(
            database_path=str(tmp_path / "echo.sqlite3"),
            worker_poll_interval_seconds=0.01,
        ),
        StubCharacterAgent(),
    )
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = None
            for _ in range(100):
                response = await client.get("/health/ready")
                if response.status_code == 200 and response.json()["lastWorkerLoopAt"]:
                    break
                await asyncio.sleep(0)

    assert response is not None
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["runtimeStatus"] == "started"
    assert response.json()["migrationStatus"] == "ok"
    assert response.json()["workerStatus"] == "running"
    assert response.json()["workerEnabled"] is True


@pytest.mark.asyncio
async def test_readiness_distinguishes_intentionally_disabled_worker(tmp_path) -> None:
    app = create_app(
        Settings(database_path=str(tmp_path / "echo.sqlite3"), worker_enabled=False),
        StubCharacterAgent(),
    )
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "disabled"
    assert body["runtimeStatus"] == "started"
    assert body["migrationStatus"] == "ok"
    assert body["workerStatus"] == "disabled"
    assert body["workerEnabled"] is False


@pytest.mark.asyncio
async def test_readiness_reports_startup_failure(tmp_path, monkeypatch) -> None:
    app = create_app(
        Settings(database_path=str(tmp_path / "echo.sqlite3")),
        StubCharacterAgent(),
    )

    async def fail_start() -> None:
        raise RuntimeError("health_startup_failure")

    monkeypatch.setattr(app.state.runtime, "start", fail_start)
    with pytest.raises(RuntimeError, match="health_startup_failure"):
        async with app.router.lifespan_context(app):
            pass

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["runtimeStatus"] == "failed"
    assert body["migrationStatus"] == "failed"
    assert body["workerStatus"] == "not_started"
    assert body["failureCode"] == "runtimeerror"


@pytest.mark.asyncio
async def test_readiness_reports_unexpected_worker_exit(tmp_path, monkeypatch) -> None:
    app = create_app(
        Settings(
            database_path=str(tmp_path / "echo.sqlite3"),
            worker_poll_interval_seconds=0.01,
        ),
        StubCharacterAgent(),
    )
    async with app.router.lifespan_context(app):
        worker = app.state.worker

        async def fail_run_once() -> bool:
            raise RuntimeError("health_worker_failure")

        monkeypatch.setattr(worker, "run_once", fail_run_once)
        worker._wake.set()
        for _ in range(100):
            if worker.failure is not None:
                break
            await asyncio.sleep(0)

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["runtimeStatus"] == "started"
    assert body["migrationStatus"] == "ok"
    assert body["workerStatus"] == "failed"
    assert body["failureCode"] == "runtimeerror"


@pytest.mark.asyncio
async def test_development_cors_allows_local_s2_frontend() -> None:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.options(
            "/message/send",
            headers={
                "Origin": "http://127.0.0.1:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
