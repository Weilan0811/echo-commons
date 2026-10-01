from __future__ import annotations

import sqlite3

from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog
from echo_commons.shared.errors import ConflictError


class CharacterIdentity:
    def __init__(self, instances: InstanceReader, catalog: BlueprintCatalog) -> None:
        self.instances, self.catalog = instances, catalog

    def name(self, connection: sqlite3.Connection, community_id: str, character_id: str) -> str:
        instance = self.instances.get(connection, community_id, character_id)
        blueprint = self.catalog.blueprint(instance.blueprint_id)
        if blueprint.version != instance.blueprint_version:
            raise ConflictError("Bound blueprint version is unavailable")
        return blueprint.display_name
