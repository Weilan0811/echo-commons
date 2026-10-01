import asyncio

from echo_commons.modules.social.planner import TurnPlanner


class SocialWorker:
    def __init__(self, planner: TurnPlanner) -> None:
        self.planner = planner

    async def run_once(self) -> bool:
        return bool(await asyncio.to_thread(self.planner.plan))
