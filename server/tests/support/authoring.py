import time
from uuid import uuid4

import pytest


def create_draft(client, name="林夏", **fields):
    body = {
        "player_id": "alice",
        "draft_id": str(uuid4()),
        "display_name": name,
        "description": "平时安静，熟悉以后喜欢开玩笑。玩游戏很认真，输了会嘴硬。",
        **fields,
    }
    response = client.post("/api/character-drafts", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


def action(client, draft, path, **fields):
    response = client.post(
        f"/api/character-drafts/{draft['draft_id']}/{path}",
        json={"player_id": "alice", "expected_revision": draft["revision"], **fields},
    )
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, draft):
    for stage in ("basic", "story", "interview"):
        present = stage == "basic" or bool(draft["content"][stage])
        if present and draft["workflow"][stage] != "accepted":
            draft = action(client, draft, f"stages/{stage}/confirm")
    if draft["workflow"]["documents_review"] != "accepted":
        draft = action(client, draft, "documents/confirm", acknowledge_documents_match=True)
    body = {
        "player_id": "alice",
        "expected_revision": draft["revision"],
        "acknowledge_fixed_background": True,
    }
    response = client.post(f"/api/character-drafts/{draft['draft_id']}/confirm", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


def wait_turn(client, conversation, *, after=None):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        turns = client.get(
            f"/api/conversations/{conversation}/turns",
            params={
                "player_id": "alice",
            },
        ).json()
        if turns and turns[-1]["status"] == "completed" and turns[-1]["social_turn_id"] != after:
            assert all(
                item["status"] == "completed"
                for item in turns[-1]["participation"]
                if item["status"] != "silent"
            ), turns
            return turns[-1]
        time.sleep(0.1)
    pytest.fail("Real model conversation did not complete")
