from support.authoring import confirm, create_draft
from support.http import create_group


def create_authored(client):
    create_group(client)
    draft, _ = create_draft(
        client,
        story=(
            "小时候住在青石镇，外婆教我修理旧钟。外婆留下的铜钥匙一直保存在我的抽屉里。"
            "我习惯每周末擦拭钟表，喜欢阴凉安静的房间。"
        ),
    )
    blueprint, _ = confirm(client, draft)
    response = client.post(
        "/api/communities/community/characters",
        json=dict(
            player_id="alice",
            blueprint_id=blueprint["blueprint_id"],
            character_id="authored",
            memory_mode="full",
        ),
    )
    assert response.status_code == 201, response.text
    app = client.app.state.application
    assert app.supervisor.workers["memory-preparation"].prepare_materials()
    assert app.supervisor.workers["memory-initialization"].advance()
    return app
