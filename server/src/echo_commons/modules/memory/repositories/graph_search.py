from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.organization import normalize_alias


class MemoryGraphSearch:
    def expand(self, connection, scope, query, direct_ids, *, entity_limit, edge_limit):
        query = normalize_alias(query)
        entities = tuple(
            connection.execute(
                "SELECT e.*,a.normalized_alias FROM memory_entities e JOIN memory_entity_aliases a "
                "USING(entity_id,character_id) WHERE e.community_id=? AND e.character_id=? "
                "AND e.created_at_utc<=? AND a.created_at_utc<=? "
                "AND e.invalidated_at_utc IS NULL AND a.invalidated_at_utc IS NULL "
                "ORDER BY e.created_at_utc,e.entity_id",
                (
                    scope.community_id,
                    scope.character_id,
                    utc_text(scope.observed_at_utc),
                    utc_text(scope.observed_at_utc),
                ),
            )
        )
        links = tuple(
            connection.execute(
                "SELECT * FROM memory_entry_entities WHERE character_id=? AND created_at_utc<=?",
                (scope.character_id, utc_text(scope.observed_at_utc)),
            )
        )
        seeds = []
        for row in entities:
            if (
                row["normalized_alias"] in query
                or any(
                    item["entity_id"] == row["entity_id"] and item["memory_id"] in direct_ids
                    for item in links
                )
            ) and row["entity_id"] not in seeds:
                seeds.append(row["entity_id"])
        seeds = seeds[:entity_limit]
        if not seeds:
            return {}
        reasons = {identity: f"entity:{identity}" for identity in seeds}
        placeholders = ",".join("?" for _ in seeds)
        for edge in connection.execute(
            "SELECT g.* FROM memory_edges g JOIN memory_entities f ON "
            "f.character_id=g.character_id AND f.entity_id=g.from_entity_id "
            "JOIN memory_entities t ON t.character_id=g.character_id "
            "AND t.entity_id=g.to_entity_id "
            "WHERE g.character_id=? AND g.created_at_utc<=? "
            "AND g.invalidated_at_utc IS NULL AND f.invalidated_at_utc IS NULL "
            "AND t.invalidated_at_utc IS NULL "
            f"AND (g.from_entity_id IN ({placeholders}) OR g.to_entity_id IN ({placeholders})) "
            "ORDER BY g.confidence DESC,g.edge_id LIMIT ?",
            (scope.character_id, utc_text(scope.observed_at_utc), *seeds, *seeds, edge_limit),
        ):
            other = (
                edge["to_entity_id"] if edge["from_entity_id"] in seeds else edge["from_entity_id"]
            )
            reasons.setdefault(other, f"edge:{edge['edge_id']}:{edge['edge_kind']}")
        return {
            item["memory_id"]: reasons[item["entity_id"]]
            for item in links
            if item["entity_id"] in reasons
        }
