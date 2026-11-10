import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from itertools import count

from echo_commons.execution.contracts import SchedulingLane
from echo_commons.execution.scheduling import current_lane, weighted_cycle
from echo_commons.infrastructure.models.protocol import (
    BeforeModelRequest,
    ModelGateway,
    ModelRequest,
    ModelResponse,
)


class ModelBudget:
    def __init__(self, gateway: ModelGateway, concurrency: int, *, weights=None) -> None:
        if concurrency < 1:
            raise ValueError("Model concurrency must be positive")
        self.gateway = gateway
        self._concurrency = concurrency
        self._active = 0
        self._condition = asyncio.Condition()
        self._waiting: set[tuple[SchedulingLane, int]] = set()
        self._order = count()
        self._cycle = weighted_cycle(
            weights
            or {
                SchedulingLane.TURN: 2,
                SchedulingLane.EXCHANGE: 2,
                SchedulingLane.BACKGROUND: 1,
            }
        )
        self._position = 0
        self._reserved = ContextVar(f"model_budget_{id(self)}", default=False)

    @asynccontextmanager
    async def reservation(self, lane: SchedulingLane | None = None):
        async with self.slot(lane):
            token = self._reserved.set(True)
            try:
                yield
            finally:
                self._reserved.reset(token)

    @asynccontextmanager
    async def slot(self, lane: SchedulingLane | None = None):
        # 同一次串行生成及其工具检索复用已经取得的名额。
        if self._reserved.get():
            yield
            return
        ticket = (lane or current_lane.get() or SchedulingLane.EXCHANGE, next(self._order))
        async with self._condition:
            self._waiting.add(ticket)
            try:
                await self._condition.wait_for(
                    lambda: self._active < self._concurrency and ticket == self._next_ticket()[0]
                )
                _, position = self._next_ticket()
                self._position = (position + 1) % len(self._cycle)
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

    def _next_ticket(self):
        for offset in range(len(self._cycle)):
            position = (self._position + offset) % len(self._cycle)
            waiting = [ticket for ticket in self._waiting if ticket[0] == self._cycle[position]]
            if waiting:
                return min(waiting, key=lambda ticket: ticket[1]), position
        raise RuntimeError("Model capacity requested without a waiting ticket")

    async def generate(
        self, request: ModelRequest, *, before_request: BeforeModelRequest | None = None
    ) -> ModelResponse:
        fallback = (
            SchedulingLane.EXCHANGE
            if request.output_contract.kind.startswith(
                ("character_message", "character_expression", "activity_")
            )
            else SchedulingLane.BACKGROUND
        )
        async with self.slot(current_lane.get() or fallback):
            return await self.gateway.generate(request, before_request=before_request)
