import asyncio

from echo_commons.infrastructure.observability.trace_delivery import TraceDelivery


class TraceWorker:
    def __init__(self, delivery: TraceDelivery) -> None:
        self.delivery = delivery

    async def run_once(self) -> bool:
        return bool(await asyncio.to_thread(self.delivery.deliver_once))
