import asyncio
from contextlib import asynccontextmanager
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

    @asynccontextmanager
    async def slot(self, priority: int = 0):
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
        priority = 0 if request.output_contract.schema_id == "character_message.v1" else 1
        async with self.slot(priority):
            return await self.gateway.generate(request, before_request=before_request)
