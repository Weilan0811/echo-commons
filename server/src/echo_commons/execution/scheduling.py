import asyncio
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace

from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import SchedulingLane

current_lane = ContextVar("execution_scheduling_lane", default=None)


@contextmanager
def scheduling_context(lane):
    token = current_lane.set(lane)
    try:
        yield
    finally:
        current_lane.reset(token)


def weighted_cycle(weights: Mapping[SchedulingLane, int]) -> tuple[SchedulingLane, ...]:
    if not weights or any(value < 1 for value in weights.values()):
        raise ValueError("Scheduling weights must be positive")
    return tuple(
        lane
        for index in range(max(weights.values()), 0, -1)
        for lane, weight in weights.items()
        if index <= weight
    )


@dataclass(frozen=True, slots=True)
class QueueRegistration:
    queue: object
    lanes: Mapping[str, SchedulingLane]


class SchedulingQueue:
    def __init__(self, database, recorder, registrations, weights):
        self.database, self.recorder = database, recorder
        self.registrations = tuple(registrations)
        self.cycle = weighted_cycle(weights)
        self._queues = {
            kind: registration.queue
            for registration in self.registrations
            for kind in registration.lanes
        }
        for registration in self.registrations:
            registration.queue.scheduling = self

    def occupancies_in(self, connection):
        return tuple(
            occupancy
            for registration in self.registrations
            for occupancy in registration.queue.occupancies_in(connection)
        )

    @staticmethod
    def allowed(candidate, occupancies):
        required = set(candidate.required_scopes)
        return not any(
            (item.task_kind, item.task_id) != (candidate.task_kind, candidate.task_id)
            and required.intersection(item.scopes)
            and (
                item.waiting_since is None
                or item.waiting_since
                < (candidate.created_at_utc, candidate.task_kind, candidate.task_id)
            )
            for item in occupancies
        )

    def allowed_in(self, connection, candidate):
        return self.allowed(candidate, self.occupancies_in(connection))

    def waiting_scopes_in(self, connection):
        scopes = {}
        for registration in self.registrations:
            for scope, lane in registration.queue.waiting_scopes_in(connection).items():
                if scope not in scopes or lane == SchedulingLane.TURN:
                    scopes[scope] = lane
        return scopes

    async def claim(self, owner, now):
        return await asyncio.to_thread(self._claim, owner)

    def _claim(self, owner):
        if not owner.strip():
            raise ValueError("Worker identity is required")
        with self.database.transaction() as connection:
            now = utc_now()
            for registration in self.registrations:
                registration.queue.reconcile_in(connection, now)
            occupied = self.occupancies_in(connection)
            candidates = []
            for registration in self.registrations:
                for candidate in registration.queue.candidates_in(connection, now):
                    if self.allowed(candidate, occupied):
                        lane = candidate.lane or registration.lanes[candidate.task_kind]
                        candidates.append((lane, candidate, registration.queue))
            position = connection.execute(
                "SELECT next_position FROM execution_scheduling WHERE scheduler_id=1"
            ).fetchone()[0]
            for offset in range(len(self.cycle)):
                slot = (position + offset) % len(self.cycle)
                ready = [item for item in candidates if item[0] == self.cycle[slot]]
                if not ready:
                    continue
                _, candidate, queue = min(
                    ready,
                    key=lambda item: (
                        item[1].available_at_utc,
                        item[1].created_at_utc,
                        item[1].task_kind,
                        item[1].task_id,
                    ),
                )
                lease = queue.claim_in(connection, owner, now, task_id=candidate.task_id)
                if lease is not None:
                    lease = replace(lease, scheduling_lane=self.cycle[slot])
                    connection.execute(
                        "UPDATE execution_scheduling SET next_position=? WHERE scheduler_id=1",
                        ((slot + 1) % len(self.cycle),),
                    )
                    return lease
            return None

    async def renew(self, lease, now):
        return await self._queues[lease.task_kind].renew(lease, now)

    async def recover(self, now):
        recovered = 0
        for registration in self.registrations:
            recovered += await registration.queue.recover(now)
        return recovered

    async def apply_recovery(self, lease, now, recovery, observation=None):
        return await self._queues[lease.task_kind].apply_recovery(lease, now, recovery, observation)
