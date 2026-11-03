import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
from dataclasses import replace
from functools import partial

import pytest
from fastapi.testclient import TestClient
from support.activity_actions import ALICE, create_character_black, play_in
from support.application import settings_for
from support.games import operation
from support.migrations import load_history

from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.app.main import create_app
from echo_commons.app.settings import Settings
from echo_commons.execution.clock import utc_now
from echo_commons.modules.activities.tasks.scheduling import ActivitySchedulingQueue


def settings_with_history(tmp_path):
    database = load_history(31, tmp_path / "history.sqlite3")
    return settings_for(tmp_path, workers=False).model_copy(
        update={
            "database_path": str(database.path),
            "max_agent_attempts": 1,
            "retry_backoff_seconds": 0,
            "model_concurrency": 1,
        }
    )


def expire_legacy(client):
    app = client.app.state.application
    policy = app.queue.policy
    app.queue.policy = replace(policy, lease_seconds=0.02)
    for _ in range(app.settings.max_agent_attempts):
        lease = client.portal.call(app.queue.claim, "interrupted-legacy", utc_now())
        assert lease is not None
        time.sleep(0.03)
        assert client.portal.call(app.queue.recover, utc_now()) == 1
    app.queue.policy = policy
    app.activity_coordinator.scan()


def scheduler(client):
    return client.app.state.application.supervisor.workers["activities-0"].queue


def claim(client, owner="test-worker", queue=None):
    return client.portal.call((queue or scheduler(client)).claim, owner, utc_now())


def pending_games(client, count):
    app = client.app.state.application
    games = [create_character_black(app) for _ in range(count)]
    app.activity_coordinator.scan()
    return games


@pytest.mark.parametrize("task_weight", [1, 2, 3])
def test_busy_judgment_queue_gives_expression_its_weighted_turn(tmp_path, task_weight):
    settings = settings_with_history(tmp_path).model_copy(
        update={"activity_task_weight": task_weight}
    )
    with TestClient(create_app(settings)) as client:
        expire_legacy(client)
        pending_games(client, 5)
        leases = [claim(client) for _ in range(task_weight)]
        assert all(lease.task_kind == "activity_turn" for lease in leases)
        app = client.app.state.application
        assert client.portal.call(app.supervisor.workers["activities-0"].run_once)
        with app.database.read() as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM activity_tasks WHERE status='pending'"
                ).fetchone()[0]
                == 5 - task_weight
            )
        with app.database.read() as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE activity_result_id IS NOT NULL"
                ).fetchone()[0]
                == 1
            )
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_parallel_workers_share_cursor_and_never_claim_same_task(tmp_path):
    with TestClient(create_app(settings_with_history(tmp_path))) as client:
        expire_legacy(client)
        pending_games(client, 4)
        app = client.app.state.application
        second = ActivitySchedulingQueue(
            app.activity_queue,
            app.activity_expressions.queue,
            task_weight=2,
            expression_weight=1,
        )
        with ThreadPoolExecutor(max_workers=3) as workers:
            leases = tuple(
                workers.map(
                    lambda index: claim(client, f"worker-{index}", second if index % 2 else None),
                    range(3),
                )
            )
        assert len({lease.task_id for lease in leases}) == 3
        assert sorted(lease.task_kind for lease in leases) == [
            "activity_expression",
            "activity_turn",
            "activity_turn",
        ]


def test_restart_continues_shared_cursor(tmp_path):
    settings = settings_with_history(tmp_path)
    with TestClient(create_app(settings)) as client:
        expire_legacy(client)
        pending_games(client, 4)
        assert claim(client).task_kind == "activity_turn"
    with TestClient(create_app(settings)) as client:
        assert claim(client).task_kind == "activity_turn"
        assert claim(client).task_kind == "activity_expression"


def test_empty_judgment_queue_is_skipped_and_idle_claim_does_not_advance(tmp_path):
    with TestClient(create_app(settings_with_history(tmp_path))) as client:
        expire_legacy(client)
        assert claim(client).task_kind == "activity_expression"
        assert claim(client) is None
        app = client.app.state.application
        with app.database.read() as connection:
            assert (
                connection.execute("SELECT next_position FROM activity_scheduling").fetchone()[0]
                == 0
            )
        pending_games(client, 1)
        assert claim(client).task_kind == "activity_turn"


def new_turn_for_original_character(client):
    app = client.app.state.application
    with app.database.read() as connection:
        old = connection.execute("SELECT * FROM activity_tasks LIMIT 1").fetchone()
        game = old["game_id"]
        context = app.game_queries.participant_context(connection, "community", ALICE, game)
        view = app.games.read_view(connection, context.access)
    with app.database.transaction() as connection:
        play_in(app, connection, game, ALICE, view.opportunities[0].legal_actions[0])
    (identity,) = app.activity_coordinator.scan()
    with app.database.read() as connection:
        return dict(app.activity_queue.repository.get(connection, identity))


def test_frozen_judgment_blocks_expression_and_can_be_reclaimed(tmp_path):
    with TestClient(create_app(settings_with_history(tmp_path))) as client:
        expire_legacy(client)
        app = client.app.state.application
        task = new_turn_for_original_character(client)
        client.portal.call(
            partial(
                app.activity_context.prepare_turn,
                "community",
                "first",
                task["game_id"],
                input_id=task["input_id"],
                participation_id=task["participation_id"],
            )
        )
        assert (
            client.portal.call(app.activity_expressions.queue.claim, "blocked", utc_now()) is None
        )
        assert claim(client).task_id == task["task_id"]


def test_unfrozen_new_turn_waits_for_expression_and_its_real_lease_recovery(tmp_path):
    settings = settings_with_history(tmp_path).model_copy(update={"max_agent_attempts": 3})
    with TestClient(create_app(settings)) as client:
        expire_legacy(client)
        app = client.app.state.application
        task = new_turn_for_original_character(client)
        queue = app.activity_expressions.queue
        queue.policy = replace(queue.policy, lease_seconds=0.2)
        expression = claim(client, queue=queue)
        assert expression is not None
        assert claim(client) is None
        app.activity_expressions.prepare(expression)
        time.sleep(0.21)
        assert client.portal.call(scheduler(client).recover, utc_now()) == 1
        resumed = claim(client)
        assert resumed.task_id == expression.task_id and resumed.generation > expression.generation
        assert resumed.task_kind == "activity_expression"
        client.portal.call(app.activity_expressions.execute, resumed)
        assert claim(client).task_id == task["task_id"]


def test_observation_runs_while_judgment_waits_for_real_model_capacity(tmp_path):
    with TestClient(create_app(settings_with_history(tmp_path))) as client:
        expire_legacy(client)
        app = client.app.state.application
        pending_games(client, 1)
        worker = app.supervisor.workers["activities-0"]
        backend = app.activity_execution.agents.bindings[InvocationPurpose.ACTIVITY_TURN].backend
        budget = backend._loop.gateway
        slots = AsyncExitStack()

        async def occupy_and_dispatch():
            for _ in range(app.settings.model_concurrency):
                await slots.enter_async_context(budget.slot())
            running = asyncio.create_task(worker.run_once())
            async with asyncio.timeout(20):
                while not budget._waiting:
                    assert not running.done()
                    await asyncio.sleep(0.01)
            return running

        running = client.portal.call(occupy_and_dispatch)
        try:
            other = create_character_black(app)
            with app.database.read() as connection:
                participation = app.game_queries.participant_context(
                    connection, "community", ALICE, other
                ).access.participation_id
            operation(client, other, "resign", participation_id=participation)
            assert not client.portal.call(app.supervisor.workers["activity-observation"].run_once)
            assert not running.done()
            with app.database.read() as connection:
                assert (
                    connection.execute(
                        "SELECT status FROM activity_reaction_opportunities WHERE game_id=? "
                        "AND kind='settlement'",
                        (other,),
                    ).fetchone()[0]
                    == "arranged"
                )
        finally:

            async def release():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
                await slots.aclose()

            client.portal.call(release)
        assert worker.dispatcher.active_task_id is None


@pytest.mark.parametrize("weight", [0, -1])
def test_nonpositive_weights_are_rejected(tmp_path, weight):
    with pytest.raises(ValueError):
        Settings.model_validate(
            {
                **settings_for(tmp_path, workers=False).model_dump(),
                "activity_task_weight": weight,
            }
        )
