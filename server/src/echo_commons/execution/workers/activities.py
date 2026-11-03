import asyncio

from echo_commons.execution.clock import utc_now
from echo_commons.execution.dispatcher import TaskDispatcher
from echo_commons.modules.activities.coordination import ActivityCoordinator
from echo_commons.modules.activities.tasks.scheduling import ActivitySchedulingQueue


class ActivityWorker:
    def __init__(
        self,
        coordinator: ActivityCoordinator,
        queue: ActivitySchedulingQueue,
        dispatcher: TaskDispatcher,
    ) -> None:
        self.coordinator, self.queue, self.dispatcher = coordinator, queue, dispatcher

    async def run_once(self) -> bool:
        await asyncio.to_thread(self.coordinator.scan)
        await self.queue.recover(utc_now())
        return await self.dispatcher.dispatch_once()


class ActivityObservationWorker:
    def __init__(self, reactions):
        self.reactions = reactions

    async def run_once(self):
        await asyncio.to_thread(self.reactions.scan)
        # 扫描始终使用后台轮询间隔，机会产生后也不立即反复扫描。
        return False
