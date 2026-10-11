from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.exceptions import ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.shared.errors import ConflictError, NotFoundError

if TYPE_CHECKING:
    from echo_commons.app.composition import Application


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


BUSINESS_RESPONSES = {
    400: {"model": ErrorResponse, "description": "业务输入或游标无效"},
    404: {"model": ErrorResponse, "description": "对象不存在或不属于请求范围"},
    409: {"model": ErrorResponse, "description": "业务状态或请求内容冲突"},
    500: {"model": ErrorResponse, "description": "响应或存储不可用"},
    503: {"model": ErrorResponse, "description": "存储暂时不可用"},
}


def application_for(request: Request) -> Application:
    return request.app.state.application


def register_errors(app: FastAPI) -> None:
    @app.exception_handler(ValidationError)
    @app.exception_handler(ResponseValidationError)
    async def invalid_response(request: Request, error: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "invalid_response", "message": "Response is unavailable"}},
        )

    @app.exception_handler(NotFoundError)
    async def not_found(request: Request, error: NotFoundError):
        return JSONResponse(
            status_code=404, content={"error": {"code": error.code, "message": str(error)}}
        )

    @app.exception_handler(ConflictError)
    async def conflict(request: Request, error: ConflictError):
        return JSONResponse(
            status_code=409, content={"error": {"code": error.code, "message": str(error)}}
        )

    @app.exception_handler(ValueError)
    async def invalid(request: Request, error: ValueError):
        return JSONResponse(
            status_code=400,
            content={
                "error": {"code": getattr(error, "code", "invalid_request"), "message": str(error)}
            },
        )

    @app.exception_handler(StorageError)
    async def storage(request: Request, error: StorageError):
        return JSONResponse(
            status_code=503 if error.retryable else 500,
            content={"error": {"code": "storage_unavailable", "message": "Storage is unavailable"}},
        )
