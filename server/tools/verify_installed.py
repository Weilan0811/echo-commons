import argparse
import json
import time
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

import echo_commons
from echo_commons.app.main import create_app
from echo_commons.app.settings import load_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", required=True)
    arguments = parser.parse_args()
    package_path = Path(echo_commons.__file__).resolve()
    assert "site-packages" in package_path.parts, package_path
    resources = files("echo_commons")
    assert resources.joinpath("infrastructure/database/sql/0001_initial.sql").is_file()
    assert resources.joinpath("resources/config/settings.toml").is_file()
    assert resources.joinpath("resources/examples/group.json").is_file()
    settings = load_settings(arguments.settings).model_copy(
        update={"quiet_window_seconds": 0, "worker_poll_interval_seconds": 0.05}
    )
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/conversations/example-conversation/messages",
            json={
                "player_id": "example-alice",
                "client_message_id": str(uuid4()),
                "text": "两位小槿，请各自用一句话说说今天想一起做什么。",
            },
        )
        assert response.status_code == 202, response.text
        deadline = time.monotonic() + 120
        while True:
            response = client.get(
                "/api/conversations/example-conversation/turns",
                params={"player_id": "example-alice"},
            )
            assert response.status_code == 200, response.text
            turns = response.json()
            if turns and turns[-1]["status"] == "completed":
                break
            assert time.monotonic() < deadline, turns
            time.sleep(0.1)
        response = client.get(
            "/api/conversations/example-conversation/messages",
            params={"player_id": "example-bob"},
        )
        assert response.status_code == 200, response.text
        replies = [
            message
            for message in response.json()["messages"]
            if message["sender"]["kind"] == "character"
        ]
        assert {message["sender"]["actor_id"] for message in replies} == {
            "example-jin-one",
            "example-jin-two",
        }
        assert all(message["text"] for message in replies)
        assert client.get("/health/ready").status_code == 200
        with app.state.application.database.read() as connection:
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        clients = tuple(app.state.application.gateway._clients.values())
    assert clients and all(model_client.is_closed() for model_client in clients)
    assert app.state.application.supervisor._tasks == []
    print(
        json.dumps(
            {
                "version": echo_commons.__version__,
                "installed_package": str(package_path),
                "schema_resources": True,
                "real_character_replies": len(replies),
                "turn_status": turns[-1]["status"],
                "foreign_key_errors": 0,
                "clients_closed": True,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
