from __future__ import annotations

from fastapi import Request

from echo_commons.runtime.application_runtime import ApplicationRuntime


async def get_runtime(request: Request) -> ApplicationRuntime:
    runtime: ApplicationRuntime = request.app.state.runtime
    await runtime.ensure_started()
    return runtime
