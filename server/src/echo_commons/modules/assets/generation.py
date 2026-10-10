import json
from datetime import datetime, timedelta
from importlib.resources import files
from uuid import uuid4

import yaml

from echo_commons.execution.clock import utc_now
from echo_commons.modules.assets.domain import SPECS
from echo_commons.modules.characters.repositories.authoring import AuthoringRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.errors import ConflictError, IdempotencyConflict, NotFoundError
from echo_commons.shared.management import read_page


class ImageGenerations:
    def __init__(self, database, gateway, settings):
        self.database, self.gateway, self.settings = database, gateway, settings
        resource = files("echo_commons.resources")
        self.prompt_root = resource.joinpath("prompts/assets")
        self.styles = yaml.safe_load(
            resource.joinpath("assets/generation_styles.yaml").read_text(encoding="utf-8")
        )["styles"]

    def available_styles(self):
        return [
            {key: value for key, value in style.items() if key != "prompt"} for style in self.styles
        ]

    def prompt(self, request, connection):
        style = next((s for s in self.styles if s["style_id"] == request.style_id), None)
        if style is None or request.purpose not in style["purposes"]:
            raise ValueError("Generation style is unavailable for this purpose")
        description = request.description
        if request.draft_id:
            row = AuthoringRepository().draft(connection, request.draft_id, request.player_id)
            if row["revision"] != request.revision:
                raise ConflictError("Character draft revision has changed")
            content = json.loads(row["content_json"])
            description = "\n".join([content["display_name"], content["description"], description])
        return "\n\n".join(
            [
                self.prompt_root.joinpath("common.md").read_text(encoding="utf-8"),
                self.prompt_root.joinpath(f"{request.purpose}.md").read_text(encoding="utf-8"),
                style["prompt"],
                "场景环境：\n" + request.scene_context.model_dump_json(),
                "本次描述：\n" + description + "\n外貌要求：\n" + request.appearance,
            ]
        )

    def create(self, request):
        frozen = request.model_dump_json()
        with self.database.transaction() as connection:
            CommunityRepository().player(connection, request.player_id)
            existing = connection.execute(
                "SELECT * FROM image_generations WHERE owner_player_id=? AND client_request_id=?",
                (request.player_id, request.client_request_id),
            ).fetchone()
            if existing:
                if existing["request_json"] != frozen:
                    raise IdempotencyConflict("Generation request already has different content")
                return dict(existing)
            self.gateway.require_credential()
            prompt = self.prompt(request, connection)
            width, height = SPECS[request.purpose][1]
            parameters = {
                "model": self.settings.image_model,
                "prompt": prompt,
                "n": 1,
                "resolution": "1k",
                "size": f"{width}x{height}",
            }
            generation_id = str(uuid4())
            now = utc_now()
            connection.execute(
                "INSERT INTO image_generations (generation_id,owner_player_id,"
                "client_request_id,purpose,request_json,prompt,parameters_json,status,"
                "created_at_utc,updated_at_utc,deadline_utc) VALUES (?,?,?,?,?,?,?,'queued',?,?,?)",
                (
                    generation_id,
                    request.player_id,
                    request.client_request_id,
                    request.purpose,
                    frozen,
                    prompt,
                    json.dumps(parameters),
                    now.isoformat(),
                    now.isoformat(),
                    (now + timedelta(seconds=self.settings.image_task_timeout_seconds)).isoformat(),
                ),
            )
            return dict(
                connection.execute(
                    "SELECT * FROM image_generations WHERE generation_id=?", (generation_id,)
                ).fetchone()
            )

    def get(self, generation_id, player_id):
        with self.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM image_generations WHERE generation_id=? AND owner_player_id=?",
                (generation_id, player_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Image generation does not exist")
            return dict(row)

    def fail(self, generation_id, code):
        self.update(generation_id, "failed", error_code=code)

    def management_page(self, player_id, options):
        with self.database.read() as connection:
            CommunityRepository().player(connection, player_id)
            return read_page(
                connection,
                "SELECT * FROM image_generations WHERE owner_player_id=?",
                (player_id,),
                scope={"query": "managed_image_generations", "player_id": player_id},
                order=("created_at_utc", "generation_id"),
                options=options,
                descending=True,
            )

    def update(self, generation_id, status, *, provider_task_id=None, error_code=None):
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE image_generations SET status=?,error_code=?,"
                "provider_task_id=COALESCE(?,provider_task_id),updated_at_utc=? "
                "WHERE generation_id=? AND status <> 'completed'",
                (status, error_code, provider_task_id, utc_now().isoformat(), generation_id),
            )

    def recover(self):
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE image_generations SET status='failed',"
                "error_code='submission_unknown',updated_at_utc=? "
                "WHERE status='submitting' AND provider_task_id IS NULL",
                (utc_now().isoformat(),),
            )
            connection.execute(
                "UPDATE image_generations SET status='failed',"
                "error_code='generation_timeout',updated_at_utc=? "
                "WHERE status NOT IN ('completed','failed') AND deadline_utc<=?",
                (utc_now().isoformat(), utc_now().isoformat()),
            )

    def claim(self, active):
        with self.database.transaction() as connection:
            for row in connection.execute(
                "SELECT * FROM image_generations "
                "WHERE status IN ('queued','generating','saving') ORDER BY created_at_utc"
            ):
                if row["generation_id"] in active:
                    continue
                if datetime.fromisoformat(row["deadline_utc"]) <= utc_now():
                    self._expire(connection, row["generation_id"])
                    continue
                if row["status"] == "queued":
                    connection.execute(
                        "UPDATE image_generations SET status='submitting',"
                        "updated_at_utc=? WHERE generation_id=?",
                        (utc_now().isoformat(), row["generation_id"]),
                    )
                return dict(row)
        return None

    def _expire(self, connection, generation_id):
        connection.execute(
            "UPDATE image_generations SET status='failed',"
            "error_code='generation_timeout' WHERE generation_id=?",
            (generation_id,),
        )
