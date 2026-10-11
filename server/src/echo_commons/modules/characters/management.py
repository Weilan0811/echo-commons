from dataclasses import asdict
from datetime import UTC, datetime

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.management import PageOptions, json_fields, read_page


class CharacterManagement:
    def __init__(self, database: Database, identity) -> None:
        self.database = database
        self.identity = identity
        self.instances = InstanceRepository()

    def character(self, community_id: str, character_id: str) -> dict:
        with self.database.read() as connection:
            self.instances.get(connection, community_id, character_id)
            result = dict(
                connection.execute(
                    "SELECT * FROM character_instances WHERE community_id = ? AND character_id = ?",
                    (community_id, character_id),
                ).fetchone()
            )
            display = self.identity.display(
                connection, community_id, ActorRef("character", character_id)
            )
            result.update(display_name=display.display_name, avatar_url=display.avatar_url)
            return result

    def characters(self, community_id, options):
        with self.database.read() as connection:
            CommunityRepository().get(connection, community_id)
            page = read_page(
                connection,
                "SELECT * FROM character_instances WHERE community_id=?",
                (community_id,),
                scope={"query": "management_characters", "community_id": community_id},
                order=("created_at_utc", "character_id"),
                options=options,
            )
            for row in page["items"]:
                display = self.identity.display(
                    connection, community_id, ActorRef("character", row["character_id"])
                )
                row.update(display_name=display.display_name, avatar_url=display.avatar_url)
            return page

    def states(self, community_id: str, character_id: str, options: PageOptions) -> dict:
        with self.database.read() as connection:
            self.instances.get(connection, community_id, character_id)
            page = read_page(
                connection,
                "SELECT * FROM character_state_entries WHERE community_id = ? AND character_id = ?",
                (community_id, character_id),
                scope={
                    "query": "states",
                    "community_id": community_id,
                    "character_id": character_id,
                },
                order=("recorded_at_utc", "entry_id"),
                options=options,
            )
            now = datetime.now(UTC)
            repository = StateRepository()
            active = [repository.latest(connection, character_id, kind, now) for kind in StateKind]
            return {
                "history": page,
                "effective_at_utc": now,
                "current": [asdict(entry) for entry in active if entry is not None],
            }

    def relationships(self, community_id: str, character_id: str, options: PageOptions) -> dict:
        with self.database.read() as connection:
            self.instances.get(connection, community_id, character_id)
            page = read_page(
                connection,
                "SELECT * FROM relationship_state WHERE community_id = ? "
                "AND observer_character_id = ?",
                (community_id, character_id),
                scope={
                    "query": "relationships",
                    "community_id": community_id,
                    "character_id": character_id,
                },
                order=("target_kind", "target_id"),
                options=options,
            )
            page["items"] = [json_fields(row) for row in page["items"]]
            for row in page["items"]:
                row["target_name"] = self.identity.display(
                    connection,
                    community_id,
                    ActorRef(row["target_kind"], row["target_id"]),
                ).display_name
                progress = connection.execute(
                    "SELECT f.graph_run_id,r.status,"
                    "COALESCE(f.error_code,r.last_error_code) error_code,"
                    "f.source_version,f.request_kind FROM memory_relationship_refreshes f "
                    "LEFT JOIN reflection_graph_runs r USING(graph_run_id) "
                    "WHERE f.community_id=? AND f.character_id=? AND f.target_kind=? "
                    "AND f.target_id=? ORDER BY f.created_at_utc DESC,f.rowid DESC LIMIT 1",
                    (community_id, character_id, row["target_kind"], row["target_id"]),
                ).fetchone()
                row["attitude_refresh"] = dict(progress) if progress else None
            return page

    def evidence(
        self,
        community_id: str,
        character_id: str,
        target_kind: str,
        target_id: str,
        options: PageOptions,
    ) -> dict:
        with self.database.read() as connection:
            self.instances.get(connection, community_id, character_id)
            if (
                connection.execute(
                    "SELECT 1 FROM community_members WHERE community_id = ? "
                    "AND actor_kind = ? AND actor_id = ?",
                    (community_id, target_kind, target_id),
                ).fetchone()
                is None
            ):
                raise NotFoundError("Relationship target does not belong to this community")
            page = read_page(
                connection,
                "SELECT * FROM relation_evidence WHERE community_id = ? "
                "AND observer_character_id = ? AND target_kind = ? AND target_id = ?",
                (community_id, character_id, target_kind, target_id),
                scope={
                    "query": "evidence",
                    "community_id": community_id,
                    "character_id": character_id,
                    "target_kind": target_kind,
                    "target_id": target_id,
                },
                order=("occurred_at_utc", "evidence_id"),
                options=options,
            )
            page["items"] = [json_fields(row) for row in page["items"]]
            return page
