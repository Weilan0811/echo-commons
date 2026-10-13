from echo_commons.infrastructure.database.mapping import utc_datetime
from echo_commons.modules.reflection.contracts.context import AuthorMaterialSource
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind


def author_snapshot(context, repository, connection, batch, now):
    materials = tuple(
        AuthorMaterialSource(
            source_id=row["chunk_id"],
            version=row["blueprint_version"],
            content=(f"问题：{row['question']}\n" if row["question"] else "") + row["content"],
            known_at_utc=utc_datetime(row["created_at_utc"]),
        )
        for row in repository.materials(connection, batch)
    )
    return context.prepare(
        connection,
        batch.community_id,
        batch.character_id,
        None,
        0,
        ReflectionGraphKind.MEMORY_ORGANIZE,
        "author_material_batch",
        batch.batch_id,
        batch.source_version,
        materials,
        now,
    )
