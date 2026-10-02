from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import TaskQueue
from echo_commons.execution.dispatcher import TaskDispatcher


class ReflectionWorker:
    def __init__(self, dispatcher: TaskDispatcher, queue: TaskQueue) -> None:
        self.dispatcher, self.queue = dispatcher, queue

    async def run_once(self) -> bool:
        await self.queue.recover(utc_now())
        return await self.dispatcher.dispatch_once()
