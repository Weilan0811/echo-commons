import asyncio

from echo_commons.execution.clock import utc_now
from echo_commons.execution.dispatcher import TaskDispatcher
from echo_commons.modules.activities.coordination import ActivityCoordinator
from echo_commons.modules.activities.tasks.queue import ActivityQueue


class ActivityWorker:
    def __init__(
        self, coordinator: ActivityCoordinator, queue: ActivityQueue, dispatcher: TaskDispatcher
    ) -> None:
        self.coordinator, self.queue, self.dispatcher = coordinator, queue, dispatcher
        self.expressions = None
        self.reactions = None
        self.expression_dispatcher = None

    async def run_once(self) -> bool:
        await asyncio.to_thread(self.coordinator.scan)
        await self.queue.recover(utc_now())
        if await self.dispatcher.dispatch_once():
            return True
        if self.expressions:
            await self.expressions.queue.recover(utc_now())
            if await self.expression_dispatcher.dispatch_once():
                return True
        if self.reactions:
            return bool(await asyncio.to_thread(self.reactions.scan))
        return False
