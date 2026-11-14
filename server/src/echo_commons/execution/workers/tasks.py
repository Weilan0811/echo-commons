from echo_commons.execution.clock import utc_now


class TaskWorker:
    def __init__(self, dispatcher, queue):
        self.dispatcher, self.queue = dispatcher, queue

    async def run_once(self):
        return await self.dispatcher.dispatch_once()


class TaskRecoveryWorker:
    def __init__(self, queue):
        self.queue = queue

    async def run_once(self):
        await self.queue.recover(utc_now())
        return False
