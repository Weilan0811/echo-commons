BASE = "/internal/communities/community"


def seal(client, character="first"):
    response = client.post(
        BASE + f"/characters/{character}/segments",
    )
    assert response.status_code == 200, response.text
    return response.json()
