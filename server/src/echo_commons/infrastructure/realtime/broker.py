import asyncio
from dataclasses import dataclass, field


@dataclass(eq=False)
class Subscription:
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    generation: int = 0


class EventBroker:
    def __init__(self):
        self.loop: asyncio.AbstractEventLoop | None = None
        self.subscriptions: dict[str, set[Subscription]] = {}
        self.closed = False

    def start(self):
        self.loop = asyncio.get_running_loop()
        self.closed = False

    def subscribe(self, community_id: str) -> Subscription:
        subscription = Subscription()
        self.subscriptions.setdefault(community_id, set()).add(subscription)
        return subscription

    def unsubscribe(self, community_id: str, subscription: Subscription):
        group = self.subscriptions.get(community_id)
        if group is not None:
            group.discard(subscription)
            if not group:
                del self.subscriptions[community_id]

    def notify(self, communities: frozenset[str]):
        if self.loop is not None and not self.closed:
            self.loop.call_soon_threadsafe(self._wake, communities)

    def _wake(self, communities: frozenset[str]):
        for community_id in communities:
            for subscription in self.subscriptions.get(community_id, ()):
                subscription.generation += 1
                subscription.changed.set()

    def close(self):
        self.closed = True
        self._wake(frozenset(self.subscriptions))

    async def wait(self, subscription: Subscription, generation: int):
        subscription.changed.clear()
        if subscription.generation == generation and not self.closed:
            await subscription.changed.wait()
