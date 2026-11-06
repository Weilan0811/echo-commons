import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from itertools import count

from echo_commons.infrastructure.models.protocol import (
    BeforeModelRequest,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)


class ModelBudget:
    def __init__(self, gateway: ModelGateway, concurrency: int) -> None:
        if concurrency < 1:
            raise ValueError("Model concurrency must be positive")
        self.gateway = gateway
        self._concurrency = concurrency
        self._active = 0
        self._condition = asyncio.Condition()
        self._waiting: set[tuple[int, int]] = set()
        self._order = count()
        self._reserved = ContextVar(f"model_budget_{id(self)}", default=False)

    @asynccontextmanager
    async def reservation(self, priority: int = 0):
        async with self.slot(priority):
            token = self._reserved.set(True)
            try:
                yield
            finally:
                self._reserved.reset(token)

    @asynccontextmanager
    async def slot(self, priority: int = 0):
        # 同一次串行生成及其工具检索复用已经取得的名额。
        if self._reserved.get():
            yield
            return
        ticket = (priority, next(self._order))
        async with self._condition:
            self._waiting.add(ticket)
            try:
                await self._condition.wait_for(
                    lambda: self._active < self._concurrency and ticket == min(self._waiting)
                )
                self._active += 1
            finally:
                self._waiting.remove(ticket)
                self._condition.notify_all()
        try:
            yield
        finally:
            async with self._condition:
                self._active -= 1
                self._condition.notify_all()

    async def generate(
        self, request: ModelRequest, *, before_request: BeforeModelRequest | None = None
    ) -> ModelResponse:
        priority = 0 if request.output_contract.kind == "character_message" else 1
        async with self.slot(priority):
            return await self.gateway.generate(request, before_request=before_request)
