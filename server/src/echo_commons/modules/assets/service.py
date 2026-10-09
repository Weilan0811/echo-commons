import json
from uuid import uuid4

from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.assets.images import decode_image, variants
from echo_commons.modules.assets.repository import AssetRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.errors import IdempotencyConflict, NotFoundError
from echo_commons.shared.management import read_page


class Assets:
    def __init__(self, database, storage):
        self.database, self.storage = database, storage
        self.repository = AssetRepository()

    def save(
        self,
        player_id,
        purpose,
        image,
        *,
        source="upload",
        source_asset_id=None,
        crop=None,
        request_id=None,
        request_json=None,
        generated=False,
        generation_id=None,
    ):
        asset_id = str(uuid4())
        files = variants(image, purpose, generated=generated)
        self.storage.prepare(asset_id, files)
        try:
            with self.database.transaction() as connection:
                CommunityRepository().player(connection, player_id)
                if source_asset_id:
                    self.repository.get(connection, source_asset_id, player_id)
                if request_id:
                    existing = connection.execute(
                        "SELECT * FROM image_assets WHERE owner_player_id=? AND request_id=?",
                        (player_id, request_id),
                    ).fetchone()
                    if existing:
                        self.storage.remove(asset_id)
                        if existing["request_json"] != request_json:
                            raise IdempotencyConflict("Crop request already has different content")
                        return self.repository.view(
                            connection,
                            self.repository.get(connection, existing["asset_id"], player_id),
                        )
                connection.execute(
                    "INSERT INTO image_assets (asset_id,owner_player_id,purpose,source,"
                    "source_asset_id,crop_json,request_id,request_json,created_at_utc) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        asset_id,
                        player_id,
                        purpose,
                        source,
                        source_asset_id,
                        json.dumps(crop) if crop else None,
                        request_id,
                        request_json,
                        utc_now().isoformat(),
                    ),
                )
                connection.executemany(
                    "INSERT INTO image_asset_files VALUES (?,?,?,?,?,?)",
                    [
                        (asset_id, v, f"{asset_id}/{name}", w, h, len(data))
                        for v, name, w, h, data in files
                    ],
                )
                if generation_id:
                    connection.execute(
                        "UPDATE image_generations SET status='completed',asset_id=?,"
                        "updated_at_utc=? WHERE generation_id=?",
                        (asset_id, utc_now().isoformat(), generation_id),
                    )
                return self.repository.view(connection, self.repository.get(connection, asset_id))
        except Exception:
            self.storage.remove(asset_id)
            raise

    def upload(self, player_id, purpose, data):
        if purpose == "character_avatar":
            raise ValueError("Create an avatar by cropping an illustration")
        limit = 5 if purpose == "character_illustration" else 8
        if len(data) > limit * 1024 * 1024:
            raise ValueError("Upload exceeds the purpose size limit")
        with self.database.read() as connection:
            CommunityRepository().player(connection, player_id)
        return self.save(player_id, purpose, decode_image(data))

    def get(self, asset_id, player_id):
        with self.database.read() as connection:
            return self.repository.view(
                connection, self.repository.get(connection, asset_id, player_id)
            )

    def page(self, player_id, purpose, options):
        with self.database.read() as connection:
            CommunityRepository().player(connection, player_id)
            page = read_page(
                connection,
                "SELECT * FROM image_assets WHERE owner_player_id=? AND status='available' "
                "AND (? IS NULL OR purpose=?)",
                (player_id, purpose, purpose),
                scope={"query": "assets", "player_id": player_id, "purpose": purpose},
                order=("created_at_utc", "asset_id"),
                options=options,
            )
            page["items"] = [self.repository.view(connection, row) for row in page["items"]]
            return page

    def file(self, asset_id, variant):
        with self.database.read() as connection:
            self.repository.get(connection, asset_id)
            row = connection.execute(
                "SELECT relative_path FROM image_asset_files WHERE asset_id=? AND variant=?",
                (asset_id, variant),
            ).fetchone()
            if row is None:
                raise NotFoundError("Image variant does not exist")
            return self.storage.root / row["relative_path"]

    def crop(self, asset_id, request):
        frozen = json.dumps({"asset_id": asset_id, **request.model_dump()}, sort_keys=True)
        with self.database.read() as connection:
            row = self.repository.get(connection, asset_id, request.player_id)
            if row["purpose"] != "character_illustration":
                raise ValueError("Avatar source must be a character illustration")
        image = decode_image(self.file(asset_id, "standard").read_bytes())
        if request.x + request.size > image.width or request.y + request.size > image.height:
            raise ValueError("Crop extends outside the illustration")
        image = image.crop(
            (request.x, request.y, request.x + request.size, request.y + request.size)
        )
        return self.save(
            request.player_id,
            "character_avatar",
            image,
            source="derived",
            source_asset_id=asset_id,
            crop=request.model_dump(include={"x", "y", "size"}),
            request_id=request.client_request_id,
            request_json=frozen,
        )

    def delete(self, asset_id, player_id):
        with self.database.transaction() as connection:
            self.repository.get(connection, asset_id, player_id)
            self.repository.require_unreferenced(connection, asset_id)
            connection.execute(
                "UPDATE image_assets SET status='deleting' WHERE asset_id=?", (asset_id,)
            )
        self.finish_delete(asset_id)

    def finish_delete(self, asset_id):
        self.storage.remove(asset_id)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE image_generations SET asset_id=NULL WHERE asset_id=?", (asset_id,)
            )
            connection.execute(
                "DELETE FROM image_assets WHERE asset_id=? AND status='deleting'", (asset_id,)
            )

    def recover(self):
        with self.database.read() as connection:
            rows = connection.execute(
                "SELECT asset_id,status FROM image_assets ORDER BY source_asset_id IS NULL"
            ).fetchall()
        for row in rows:
            if row["status"] == "deleting":
                self.finish_delete(row["asset_id"])
        self.storage.maintain({r["asset_id"] for r in rows if r["status"] == "available"})
