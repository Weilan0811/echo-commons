import sqlite3

from pydantic import TypeAdapter

from echo_commons.modules.characters.domain.authoring import AuthoringContent
from echo_commons.modules.characters.repositories.authoring import AuthoringRepository
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog, CharacterBlueprint
from echo_commons.modules.memory.domain.authored import AuthorMaterial
from echo_commons.shared.errors import ConflictError

BLUEPRINT_ADAPTER = TypeAdapter(CharacterBlueprint)


class BlueprintReader:
    def __init__(self, catalog: BlueprintCatalog) -> None:
        self.catalog = catalog
        self.agent_contract = catalog.agent_contract
        self.repository = AuthoringRepository()

    def author_materials(
        self, connection: sqlite3.Connection, blueprint_id: str, version: str
    ) -> tuple[AuthorMaterial, ...]:
        self.get(connection, blueprint_id, version)
        if not blueprint_id.startswith("custom:"):
            return ()
        row = self.repository.blueprint(connection, blueprint_id)
        content = AuthoringContent.model_validate_json(row["materials_json"])
        materials = []
        if content.story.strip():
            materials.append(AuthorMaterial("story", 0, content.story))
        materials.extend(
            AuthorMaterial("interview", index, item.answer, item.question_id, item.question)
            for index, item in enumerate(content.interview)
            if item.answer.strip()
        )
        return tuple(materials)

    def get(
        self,
        connection: sqlite3.Connection,
        blueprint_id: str,
        version: str | None = None,
    ) -> CharacterBlueprint:
        if blueprint_id.startswith("custom:"):
            row = self.repository.blueprint(connection, blueprint_id)
            blueprint = BLUEPRINT_ADAPTER.validate_json(row["resource_json"])
        else:
            blueprint = self.catalog.get(connection, blueprint_id, version)
        if version is not None and blueprint.content_version != version:
            raise ConflictError("Bound blueprint version is unavailable")
        return blueprint

    def require_instantiable(
        self,
        connection: sqlite3.Connection,
        blueprint_id: str,
        player_id: str | None,
    ) -> CharacterBlueprint:
        if blueprint_id.startswith("custom:"):
            # 私有创作不通过管理或无玩家入口绕过所有者资格。
            self.repository.blueprint(connection, blueprint_id, player_id or "")
        return self.get(connection, blueprint_id)
