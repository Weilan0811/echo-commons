import socket
import threading
import time
from contextlib import contextmanager

import httpx
import uvicorn

from echo_commons.app.main import create_app


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


def cursor(client, player="alice"):
    response = client.get("/api/communities/community/events/cursor", params={"player_id": player})
    assert response.status_code == 200
    return response.json()["cursor"]


def next_event(events, kind):
    for event in events:
        if event.event == kind:
            return event
    raise AssertionError(f"Missing event: {kind}")
