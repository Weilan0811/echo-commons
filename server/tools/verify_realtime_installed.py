import argparse
import json
import socket
import threading
import time
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import uvicorn
from httpx_sse import connect_sse

import echo_commons
from echo_commons.app.main import create_app
from echo_commons.app.settings import load_settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    arguments = parser.parse_args()
    assert "site-packages" in Path(echo_commons.__file__).parts
    assert (
        files("echo_commons")
        .joinpath("infrastructure/database/sql/0011_realtime_events.sql")
        .is_file()
    )
    with TemporaryDirectory(prefix="echo-sse-installed-") as directory:
        settings = load_settings(arguments.settings).model_copy(
            update={
                "database_path": str(Path(directory) / "application.sqlite3"),
                "log_path": str(Path(directory) / "application.log"),
                "worker_enabled": False,
            }
        )
        app = create_app(settings)
        with socket.socket() as endpoint:
            endpoint.bind(("127.0.0.1", 0))
            endpoint.listen()
            port = endpoint.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [endpoint]})
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started:
                    assert thread.is_alive() and time.monotonic() < deadline
                    time.sleep(0.02)
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
                    for player in ("alice", "bob"):
                        assert (
                            client.post(
                                "/api/players",
                                json={
                                    "player_id": player,
                                    "display_name": player,
                                },
                            ).status_code
                            == 201
                        )
                    assert (
                        client.post(
                            "/api/communities",
                            json={
                                "player_id": "alice",
                                "community_id": "community",
                                "name": "安装验证",
                            },
                        ).status_code
                        == 201
                    )
                    assert client.put("/api/communities/community/players/bob").status_code == 200
                    assert (
                        client.post(
                            "/api/communities/community/conversations",
                            json={
                                "player_id": "alice",
                                "conversation_id": "conversation",
                                "kind": "group",
                                "actors": [
                                    {"kind": "player", "actor_id": player}
                                    for player in ("alice", "bob")
                                ],
                            },
                        ).status_code
                        == 201
                    )
                    cursor = client.get(
                        "/api/communities/community/events/cursor",
                        params={
                            "player_id": "bob",
                        },
                    ).json()["cursor"]
                    with connect_sse(
                        client,
                        "GET",
                        "/api/communities/community/events",
                        params={
                            "player_id": "bob",
                            "cursor": cursor,
                        },
                    ) as stream:
                        response = client.post(
                            "/api/conversations/conversation/messages",
                            json={
                                "player_id": "alice",
                                "client_message_id": "installed",
                                "text": "安装后的真实推送验证。",
                            },
                        )
                        assert response.status_code == 202
                        for event in stream.iter_sse():
                            if event.event == "conversation.message_created":
                                assert (
                                    event.json()["message"]["message_id"]
                                    == response.json()["message_id"]
                                )
                                break
                    with app.state.application.database.read() as connection:
                        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
                        assert (
                            connection.execute(
                                "SELECT MAX(version) FROM schema_migrations"
                            ).fetchone()[0]
                            == 11
                        )
            finally:
                server.should_exit = True
                thread.join(10)
                assert not thread.is_alive()
        assert not app.state.application.realtime.broker.subscriptions
    print(json.dumps({"installed_sse": True, "schema_version": 11, "connections_closed": True}))


if __name__ == "__main__":
    main()
