import json
import sqlite3

from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.management import PageOptions, read_page


class AuthoringRepository:
    def draft(self, connection: sqlite3.Connection, draft_id: str, player_id: str) -> dict:
        row = connection.execute(
            "SELECT * FROM character_authoring_drafts WHERE draft_id=? AND owner_player_id=?",
            (draft_id, player_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Draft does not belong to this player")
        return dict(row)

    def candidate(self, connection: sqlite3.Connection, draft_id: str, candidate_id: str) -> dict:
        row = connection.execute(
            "SELECT * FROM character_authoring_candidates WHERE draft_id=? AND candidate_id=?",
            (draft_id, candidate_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Candidate does not belong to this draft")
        return dict(row)

    def blueprint(
        self,
        connection: sqlite3.Connection,
        blueprint_id: str,
        player_id: str | None = None,
    ) -> dict:
        sql = "SELECT * FROM custom_character_blueprints WHERE blueprint_id=?"
        params = (blueprint_id,)
        if player_id is not None:
            sql += " AND owner_player_id=?"
            params += (player_id,)
        row = connection.execute(sql, params).fetchone()
        if row is None:
            raise NotFoundError("Custom blueprint does not belong to this scope")
        return dict(row)

    def page(
        self,
        connection: sqlite3.Connection,
        player_id: str,
        options: PageOptions,
        *,
        blueprints: bool = False,
    ) -> dict:
        table = "custom_character_blueprints" if blueprints else "character_authoring_drafts"
        key = "blueprint_id" if blueprints else "draft_id"
        return read_page(
            connection,
            f"SELECT * FROM {table} WHERE owner_player_id=?",
            (player_id,),
            scope={"player_id": player_id, "list": table},
            order=("created_at_utc", key),
            options=options,
        )


def draft_view(row: dict) -> dict:
    return {
        "draft_id": row["draft_id"],
        "owner_player_id": row["owner_player_id"],
        "status": row["status"],
        "revision": row["revision"],
        "content": json.loads(row["content_json"]),
        "workflow": json.loads(row["workflow_json"]),
        "confirmed_blueprint_id": row["confirmed_blueprint_id"],
        "accepted_candidate_id": row["accepted_candidate_id"],
        "material_processing": "stored_only",
        "created_at_utc": row["created_at_utc"],
        "updated_at_utc": row["updated_at_utc"],
    }


def candidate_view(row: dict) -> dict:
    return {
        key: row[key]
        for key in (
            "candidate_id",
            "draft_id",
            "input_revision",
            "operation",
            "status",
            "error_code",
            "model_profile",
            "model_requests",
            "deadline_utc",
            "created_at_utc",
            "finished_at_utc",
        )
    } | {
        "output": json.loads(row["output_json"]) if row["output_json"] else None,
        "usage": json.loads(row["usage_json"]),
        "frozen_input": json.loads(row["request_json"]),
    }
