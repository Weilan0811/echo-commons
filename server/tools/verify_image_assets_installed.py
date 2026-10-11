from importlib.resources import files
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient
from PIL import Image

import echo_commons
from echo_commons.app.main import create_app
from echo_commons.app.settings import Settings


def main():
    assert "site-packages" in Path(echo_commons.__file__).parts
    root = files("echo_commons")
    for path in (
        "infrastructure/database/sql/0012_image_assets.sql",
        "infrastructure/database/sql/0013_appearance_events.sql",
        "resources/prompts/assets/common.md",
        "resources/prompts/assets/character_illustration.md",
        "resources/prompts/assets/community_cover.md",
        "resources/prompts/assets/chat_background.md",
        "resources/assets/generation_styles.yaml",
    ):
        assert root.joinpath(path).is_file(), path
    with TemporaryDirectory(prefix="echo-assets-installed-") as directory:
        temporary = Path(directory)
        settings = Settings(
            database_path=str(temporary / "database.sqlite3"),
            asset_directory=str(temporary / "images"),
            worker_enabled=False,
            model_registry_path=str(root.joinpath("resources/config/model-registry.toml")),
            model_secrets_path=str(temporary / "absent-credentials.toml"),
        )
        with TestClient(create_app(settings)) as client:
            assert (
                client.post(
                    "/api/players", json={"player_id": "author", "display_name": "作者"}
                ).status_code
                == 201
            )
            data = BytesIO()
            Image.new("RGB", (1080, 1350), (60, 80, 100)).save(data, "PNG")
            response = client.post(
                "/api/assets/images",
                data={"player_id": "author", "purpose": "character_illustration"},
                files={"file": ("picture.png", data.getvalue())},
            )
            assert response.status_code == 201, response.text
            illustration = response.json()
            response = client.post(
                f"/api/assets/{illustration['asset_id']}/avatar-crops",
                json={
                    "player_id": "author",
                    "client_request_id": "crop",
                    "x": 0,
                    "y": 0,
                    "size": 1080,
                },
            )
            assert response.status_code == 201, response.text
            avatar = response.json()
            picture = client.get(
                next(i["url"] for i in avatar["images"] if i["variant"] == "standard")
            )
            assert Image.open(BytesIO(picture.content)).size == (512, 512)
            assert (
                client.delete(f"/api/assets/{avatar['asset_id']}?player_id=author").status_code
                == 204
            )
            assert (
                client.delete(
                    f"/api/assets/{illustration['asset_id']}?player_id=author"
                ).status_code
                == 204
            )
    print("Installed image assets and resources verified")


if __name__ == "__main__":
    main()
