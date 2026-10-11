import asyncio
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import uvicorn
from historical_messages import historical_message
from httpx_sse import connect_sse
from test_application_lifecycle import settings_for
from test_http_api import create_group

from echo_commons.app.main import create_app
from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.realtime.broker import EventBroker
from echo_commons.infrastructure.realtime.stream import EventCursor
from echo_commons.modules.conversations.services.events import message_created
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.realtime import EventKind, EventReference, EventSource, record_event


@contextmanager
def running_server(settings, *, include_server=False):
    app = create_app(settings)
    endpoint = socket.socket()
    endpoint.bind(("127.0.0.1", 0))
    endpoint.listen()
    port = endpoint.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=3))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [endpoint]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline
            time.sleep(0.01)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False
        ) as client:
            result = (client, app.state.application)
            yield (*result, server) if include_server else result
    finally:
        server.should_exit = True
        thread.join(8)
        endpoint.close()
        assert not thread.is_alive()


@pytest.fixture
def live_server(tmp_path, request):
    mode = getattr(request, "param", False)
    settings = settings_for(tmp_path, workers=mode is True)
    if mode == "missing_credentials":
        settings = settings.model_copy(
            update={"model_secrets_path": str(tmp_path / "missing.toml")}
        )
    with running_server(settings, include_server=mode == "slow_network") as server:
        create_group(server[0])
        yield server


def cursor(client, player="alice"):
    response = client.get("/api/communities/community/events/cursor", params={"player_id": player})
    assert response.status_code == 200
    return response.json()["cursor"]


def send(
    client, identity="hello", conversation="conversation", player="alice", text="一起讨论下一步。"
):
    response = client.post(
        f"/api/conversations/{conversation}/messages",
        json={
            "player_id": player,
            "client_message_id": identity,
            "text": text,
        },
    )
    assert response.status_code == 202
    return response.json()


def next_event(events, kind):
    for event in events:
        if event.event == kind:
            return event
    raise AssertionError(f"Missing event: {kind}")


def stream(client, position, player="alice", headers=None):
    return connect_sse(
        client,
        "GET",
        "/api/communities/community/events",
        params={"player_id": player, "cursor": position},
        headers=headers or {},
    )


def test_real_connections_broadcast_and_resume(live_server):
    client, application = live_server
    alice, bob = cursor(client), cursor(client, "bob")
    with stream(client, alice) as first, stream(client, bob, "bob") as second:
        receipt = send(client)
        one = next_event(first.iter_sse(), "conversation.message_created")
        two = next_event(second.iter_sse(), "conversation.message_created")
        assert one.json()["message"]["message_id"] == two.json()["message"]["message_id"]
        assert one.json()["message"]["message_id"] == receipt["message_id"]
        assert "thought" not in one.json()["message"]
    later = send(client, "later")
    with stream(client, alice, headers={"Last-Event-ID": one.id}) as source:
        replay = next_event(source.iter_sse(), "conversation.message_created")
        assert replay.json()["message"]["message_id"] == later["message_id"]
    deadline = time.monotonic() + 3
    while application.realtime.broker.subscriptions:
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_initial_position_covers_loading_and_duplicate_requests(live_server):
    client, application = live_server
    position = cursor(client)
    receipt = send(client)
    assert send(client) == receipt
    history = client.get(
        "/api/conversations/conversation/messages/history", params={"player_id": "alice"}
    ).json()
    assert receipt["message_id"] in {message["message_id"] for message in history["messages"]}
    with stream(client, position) as source:
        event = next_event(source.iter_sse(), "conversation.message_created")
        assert event.json()["message"]["message_id"] == receipt["message_id"]
    with application.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM realtime_events WHERE kind='conversation.message_created'"
            ).fetchone()[0]
            == 1
        )


def test_private_events_and_filtered_checkpoint(live_server):
    client, application = live_server
    position = cursor(client, "bob")
    private = historical_message(
        application, "历史私有消息", recipients=(ActorRef("character", "first"),)
    )
    with application.database.transaction() as connection:
        message_created(connection, private)
    decoded = EventCursor.decode(position, "bob", "community")
    outgoing, after, _, _ = application.realtime.scan(decoded)
    assert [item["event"] for item in outgoing] == ["checkpoint"]
    assert after.sequence > decoded.sequence
    with stream(client, position, "bob") as source:
        assert next_event(source.iter_sse(), "checkpoint").json() == {}
    assert (
        client.post(
            "/api/communities/community/conversations",
            json={
                "player_id": "alice",
                "conversation_id": "direct",
                "kind": "direct",
                "actors": [
                    {"kind": "player", "actor_id": "alice"},
                    {"kind": "character", "actor_id": "first"},
                ],
            },
        ).status_code
        == 201
    )
    send(client, "private", "direct")
    outgoing, _, _, _ = application.realtime.scan(after)
    assert all(item["event"] == "checkpoint" for item in outgoing)


def test_membership_read_and_status_notifications(live_server):
    client, application = live_server
    before = application.realtime.current("community", "bob")
    receipt = send(client)
    application.player_conversations.mark_read("conversation", "alice", receipt["message_id"])
    application.player_conversations.mark_read("conversation", "alice", receipt["message_id"])
    outgoing, _, _, _ = application.realtime.scan(before)
    assert all(item["event"] != "conversation.read_changed" for item in outgoing)
    with application.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM realtime_events WHERE kind='conversation.read_changed'"
            ).fetchone()[0]
            == 1
        )
    application.conversations.leave("community", "conversation", ActorRef("player", "bob"))
    send(client, "during-absence")
    application.conversations.join("community", "conversation", ActorRef("player", "bob"))
    outgoing, _, _, _ = application.realtime.scan(before)
    assert sum(item["event"] == "conversation.members_changed" for item in outgoing) == 2
    messages = [item for item in outgoing if item["event"] == "conversation.message_created"]
    assert len(messages) == 1
    with stream(client, cursor(client, "bob"), "bob") as source:
        result = client.patch(
            "/api/communities/community/status",
            json={
                "player_id": "alice",
                "status": "paused",
                "expected_version": 1,
            },
        )
        assert result.status_code == 200
        assert next_event(source.iter_sse(), "community.status_changed").json() == {
            "community_id": "community",
        }


def test_transaction_rollback_and_retention(live_server):
    client, application = live_server
    before = application.realtime.current("community", "alice")
    with pytest.raises(StorageError), application.database.transaction() as connection:
        connection.execute("UPDATE communities SET status='paused' WHERE community_id='community'")
        record_event(
            connection,
            EventReference(
                EventKind.COMMUNITY,
                "community",
                "community",
                EventSource.COMMUNITY,
                "community",
            ),
        )
        # 实际数据库约束失败时，前面的状态与事件均不得提交。
        connection.execute("UPDATE communities SET state_version=-1 WHERE community_id='community'")
    assert application.realtime.current("community", "alice") == before
    send(client)
    high = application.realtime.current("community", "alice")
    with application.database.transaction() as connection:
        application.database.events.clean(connection, datetime.now(UTC) + timedelta(days=2))
    assert application.realtime.current("community", "alice") == high
    with stream(client, before.encode()) as source:
        assert next_event(source.iter_sse(), "resync_required").json() == {
            "reason": "cursor_expired"
        }
    send(client, "after-clean")
    assert application.realtime.current("community", "alice").sequence > high.sequence


def test_restart_replays_persistent_events(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    with running_server(settings) as (client, _):
        create_group(client)
        before = cursor(client)
        receipt = send(client)
    with running_server(settings) as (client, _), stream(client, before) as source:
        replay = next_event(source.iter_sse(), "conversation.message_created")
        assert replay.json()["message"]["message_id"] == receipt["message_id"]


@contextmanager
def process_server(settings, tmp_path):
    configuration = tmp_path / "server-settings.json"
    configuration.write_text(settings.model_dump_json(), encoding="utf-8")
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        port = endpoint.getsockname()[1]
    with (tmp_path / "server-process.log").open("ab") as output:
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("realtime_server_process.py")),
                str(configuration),
                str(port),
            ],
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=5, trust_env=False
            ) as client:
                deadline = time.monotonic() + 15
                while True:
                    assert process.poll() is None and time.monotonic() < deadline
                    try:
                        if client.get("/health/live").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.03)
                yield client
        finally:
            process.terminate()
            process.wait(timeout=8)


def test_killed_server_process_keeps_replay_position(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    with process_server(settings, tmp_path) as client:
        create_group(client)
        before = cursor(client)
        receipt = send(client)
    with process_server(settings, tmp_path) as client, stream(client, before) as source:
        replay = next_event(source.iter_sse(), "conversation.message_created")
        assert replay.json()["message"]["message_id"] == receipt["message_id"]


@pytest.mark.parametrize("live_server", ["slow_network"], indirect=True)
def test_slow_network_send_timeout_releases_subscription(live_server):
    client, application, server = live_server
    position = cursor(client)
    with socket.socket() as slow:
        slow.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        slow.settimeout(5)
        slow.connect(("127.0.0.1", client.base_url.port))
        path = f"/api/communities/community/events?player_id=alice&cursor={position}"
        slow.sendall(f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
        header = bytearray()
        while not header.endswith(b"\r\n\r\n"):
            header.extend(slow.recv(1))
        assert b"200 OK" in header
        protocol = next(
            connection
            for connection in tuple(server.server_state.connections)
            if connection.scope["path"].endswith("/events")
        )
        protocol.transport.get_extra_info("socket").setsockopt(
            socket.SOL_SOCKET, socket.SO_SNDBUF, 1024
        )
        for index in range(64):
            send(client, f"slow-receiver-{index}", text="slow receiver " * 4096)
            if protocol.flow.write_paused:
                break
        assert protocol.flow.write_paused
        assert application.realtime.broker.subscriptions
        deadline = time.monotonic() + 55
        while application.realtime.broker.subscriptions:
            assert time.monotonic() < deadline
            time.sleep(0.1)


def test_notification_between_scan_and_wait_is_retained():
    async def run():
        broker = EventBroker()
        broker.start()
        subscription = broker.subscribe("community")
        generation = subscription.generation
        broker.notify(frozenset({"community"}))
        await asyncio.sleep(0)
        await asyncio.wait_for(broker.wait(subscription, generation), 1)
        assert subscription.generation > generation
        broker.close()
        broker.unsubscribe("community", subscription)
        assert not broker.subscriptions

    asyncio.run(run())


@pytest.mark.parametrize("live_server", ["missing_credentials"], indirect=True)
def test_real_configuration_failure_and_player_interruption_notify_turns(live_server):
    client, application = live_server
    before = application.realtime.current("community", "alice")
    send(client)

    async def run():
        for _ in range(6):
            application.planner.plan()
            worked = await application.supervisor.workers["conversations-0"].run_once()
            if not worked:
                break
        application.planner.plan()

    asyncio.run(run())
    turns = client.get(
        "/api/conversations/conversation/turns", params={"player_id": "alice"}
    ).json()
    assert turns and turns[-1]["chain_status"] == "completed"
    assert any(item["outcome"] == "failed" for item in turns[-1]["participation"])
    outgoing, _, _, _ = application.realtime.scan(before)
    assert any(item["event"] == "conversation.turns_changed" for item in outgoing)
    send(client, "new-chain")
    application.planner.plan()
    middle = application.realtime.current("community", "alice")
    send(client, "interrupt")
    outgoing, _, _, _ = application.realtime.scan(middle)
    assert any(item["event"] == "conversation.turns_changed" for item in outgoing)


@pytest.mark.model
@pytest.mark.parametrize("live_server", [True], indirect=True)
def test_real_silence_notifies_completed_turn(live_server):
    client, _ = live_server
    with (
        httpx.Client(base_url=str(client.base_url), timeout=120) as waiting,
        stream(waiting, cursor(client)) as source,
    ):
        send(client, "silent", text="两位小槿，这次请保持沉默，不要发送任何聊天消息。")
        for event in source.iter_sse():
            if event.event != "conversation.turns_changed":
                continue
            turns = client.get(
                "/api/conversations/conversation/turns", params={"player_id": "alice"}
            ).json()
            if turns and turns[-1]["chain_status"] == "completed":
                assert any(item["outcome"] == "silent" for item in turns[-1]["participation"])
                break
        else:
            raise AssertionError("Silent chain did not finish")


def test_cursor_errors_and_cors(live_server):
    client, _ = live_server
    position = cursor(client)
    endpoint = "/api/communities/community/events"
    for params in (
        {"player_id": "alice"},
        {"player_id": "alice", "cursor": "invalid"},
        {"player_id": "bob", "cursor": position},
    ):
        assert client.get(endpoint, params=params).status_code == 400
    future = EventCursor.decode(position, "alice", "community").model_copy(
        update={"sequence": 99999}
    )
    assert (
        client.get(endpoint, params={"player_id": "alice", "cursor": future.encode()}).status_code
        == 400
    )
    assert (
        client.get(endpoint, params={"player_id": "unknown", "cursor": position}).status_code == 400
    )
    assert (
        client.options(
            endpoint,
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "last-event-id",
            },
        ).status_code
        == 200
    )


@pytest.mark.model
@pytest.mark.parametrize("live_server", [True], indirect=True)
def test_real_character_reply_reaches_sse(live_server):
    client, application = live_server
    with (
        httpx.Client(base_url=str(client.base_url), timeout=120) as waiting,
        stream(waiting, cursor(client)) as source,
    ):
        events = source.iter_sse()
        send(client, "real-character")
        event = next_event(events, "conversation.message_created")
        assert event.json()["message"]["sender"]["kind"] == "player"
        for event in events:
            if event.event == "conversation.message_created":
                message = event.json()["message"]
                if message["sender"]["kind"] == "character":
                    assert message["text"] and message["source_turn_id"]
                    assert "thought" not in message
                    break
        else:
            raise AssertionError("No character reply")
    assert application.realtime.broker.loop is not None
