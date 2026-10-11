import json

from echo_commons.modules.assets.domain import image_url
from echo_commons.shared.errors import ConflictError, NotFoundError


class AssetRepository:
    def get(self, connection, asset_id, player_id=None):
        row = connection.execute(
            "SELECT * FROM image_assets WHERE asset_id=? AND status='available'", (asset_id,)
        ).fetchone()
        if row is None or (player_id is not None and row["owner_player_id"] != player_id):
            raise NotFoundError("Image asset does not exist")
        return row

    def view(self, connection, row):
        data = dict(row)
        data["crop"] = json.loads(row["crop_json"]) if row["crop_json"] else None
        data["images"] = [
            dict(
                variant=file["variant"],
                width=file["width"],
                height=file["height"],
                byte_size=file["byte_size"],
                url=image_url(row["asset_id"], file["variant"]),
            )
            for file in connection.execute(
                "SELECT * FROM image_asset_files WHERE asset_id=? ORDER BY variant",
                (row["asset_id"],),
            )
        ]
        return data

    def bind(self, connection, owner_kind, owner_id, asset_id, player_id, purpose):
        if asset_id is not None:
            row = self.get(connection, asset_id, player_id)
            if row["purpose"] != purpose:
                raise ValueError("Image asset purpose does not match this use")
        connection.execute(
            "DELETE FROM image_asset_references WHERE owner_kind=? AND owner_id=?",
            (owner_kind, owner_id),
        )
        if asset_id is not None:
            connection.execute(
                "INSERT INTO image_asset_references VALUES (?,?,?)",
                (owner_kind, owner_id, asset_id),
            )

    def require_unreferenced(self, connection, asset_id):
        if (
            connection.execute(
                "SELECT 1 FROM image_asset_references WHERE asset_id=?", (asset_id,)
            ).fetchone()
            or connection.execute(
                "SELECT 1 FROM image_assets WHERE source_asset_id=?", (asset_id,)
            ).fetchone()
        ):
            raise ConflictError("Image asset is still referenced")
        if connection.execute(
            "SELECT 1 FROM image_generations WHERE asset_id=? "
            "AND status NOT IN ('completed','failed')",
            (asset_id,),
        ).fetchone():
            raise ConflictError("Image generation is still running")
