import asyncio
from datetime import UTC, datetime

from echo_commons.infrastructure.database.connection import Database

CLEAN_INTERVAL = 3600


class EventRetention:
    def __init__(self, database: Database):
        self.database = database
        self.stop = asyncio.Event()
        self.task: asyncio.Task | None = None

    def clean(self):
        with self.database.transaction() as connection:
            return self.database.events.clean(connection, datetime.now(UTC))

    async def start(self):
        self.stop.clear()
        await asyncio.to_thread(self.clean)
        self.task = asyncio.create_task(self.run(), name="realtime-retention")

    async def run(self):
        while not self.stop.is_set():
            try:
                await asyncio.wait_for(self.stop.wait(), CLEAN_INTERVAL)
            except TimeoutError:
                await asyncio.to_thread(self.clean)

    async def close(self):
        self.stop.set()
        if self.task is not None:
            await self.task
            self.task = None
