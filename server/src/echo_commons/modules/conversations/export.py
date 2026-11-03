from datetime import UTC, datetime

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.management import inspected_result, message_detail
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.memory.management import MemoryCollection, MemoryManagement
from echo_commons.modules.perspective.contracts import ObservationScope
from echo_commons.modules.perspective.conversation import ConversationPerspective
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.management import json_fields


class ConversationExport:
    def __init__(self, database: Database, provenance=None) -> None:
        self.database = database
        self.conversations = ConversationRepository()
        self.perspective = ConversationPerspective(
            CommunityRepository(),
            self.conversations,
            MessageRepository(),
        )
        self.memory = MemoryManagement(database, provenance)

    def export(
        self,
        community_id: str,
        conversation_id: str,
        *,
        first_sequence: int,
        through_sequence: int,
        character_id: str | None = None,
    ) -> dict:
        with self.database.read() as connection:
            conversation = self.conversations.get(connection, community_id, conversation_id)
            if not 1 <= first_sequence <= through_sequence < conversation.next_sequence:
                raise ValueError("Export range must contain existing message sequences")
            if through_sequence - first_sequence >= 10000:
                raise ValueError("One export may include at most 10000 message sequences")
            visible = None
            if character_id is not None:
                InstanceRepository().get(connection, community_id, character_id)
                visible = {
                    message.message_id
                    for message in self.perspective.messages(
                        connection,
                        ObservationScope(
                            community_id,
                            conversation_id,
                            ActorRef("character", character_id),
                            through_sequence,
                        ),
                        after=first_sequence - 1,
                    )
                }
            rows = connection.execute(
                "SELECT * FROM messages WHERE community_id = ? AND conversation_id = ? "
                "AND sequence BETWEEN ? AND ? ORDER BY sequence",
                (community_id, conversation_id, first_sequence, through_sequence),
            ).fetchall()
            rows = [row for row in rows if visible is None or row["message_id"] in visible]
            messages = [message_detail(connection, row) for row in rows]
            message_ids = {row["message_id"] for row in rows}
            references = {}

            def reference(kind, identity, version=None, owner=None, source_conversation=None):
                references[(kind, identity, owner)] = {
                    "community_id": community_id,
                    "character_id": owner,
                    "conversation_id": source_conversation,
                    "source_kind": kind,
                    "source_id": identity,
                    "source_version": version,
                }

            for row in rows:
                if row["activity_result_id"]:
                    reference(
                        "activity_result",
                        row["activity_result_id"],
                        owner=row["sender_id"],
                        source_conversation=conversation_id,
                    )
                reply = row["reply_to_message_id"]
                if reply and reply not in message_ids:
                    reference("message", reply, "1", source_conversation=conversation_id)
            turn_ids = {row["source_turn_id"] for row in rows if row["source_turn_id"]}
            result_ids = {row["result_id"] for row in rows if row["result_id"]}
            for row in connection.execute(
                "SELECT tb.social_turn_id,bm.message_id FROM social_turn_batches tb "
                "JOIN input_batch_messages bm ON bm.input_batch_id = tb.input_batch_id "
                "JOIN social_turns t ON t.social_turn_id = tb.social_turn_id "
                "WHERE t.community_id = ? AND t.conversation_id = ?",
                (community_id, conversation_id),
            ):
                if row["message_id"] in message_ids:
                    turn_ids.add(row["social_turn_id"])
            turns, tasks, results, thoughts = [], [], [], []
            for row in connection.execute(
                "SELECT * FROM social_turns WHERE community_id = ? AND conversation_id = ? "
                "ORDER BY created_at_utc,social_turn_id",
                (community_id, conversation_id),
            ):
                if row["social_turn_id"] not in turn_ids:
                    continue
                turns.append(json_fields(row))
                for source in connection.execute(
                    "SELECT bm.message_id FROM social_turn_batches tb "
                    "JOIN input_batch_messages bm ON bm.input_batch_id = tb.input_batch_id "
                    "WHERE tb.social_turn_id = ?",
                    (row["social_turn_id"],),
                ):
                    if source[0] not in message_ids:
                        reference("message", source[0], "1", source_conversation=conversation_id)
            for row in connection.execute(
                "SELECT t.*,s.initiation_id FROM conversation_tasks t "
                "JOIN social_turns s USING(social_turn_id) "
                "WHERE t.community_id = ? AND t.conversation_id = ? "
                "ORDER BY t.created_at_utc,t.task_id",
                (community_id, conversation_id),
            ):
                emitted_results = {
                    result[0]
                    for result in connection.execute(
                        "SELECT result_id FROM conversation_results WHERE task_id=?",
                        (row["task_id"],),
                    )
                }
                if row["social_turn_id"] not in turn_ids and not emitted_results & result_ids:
                    continue
                if character_id is not None and row["character_id"] != character_id:
                    continue
                task = dict(row)
                task.pop("snapshot_json")
                tasks.append(task)
                if row["initiation_id"] is not None:
                    reference(
                        "conversation_initiation",
                        row["initiation_id"],
                        owner=row["character_id"],
                        source_conversation=conversation_id,
                    )
                if row["snapshot_id"] is not None:
                    reference(
                        "context_snapshot",
                        row["snapshot_id"],
                        str(row["snapshot_schema_version"]),
                        row["character_id"],
                        conversation_id,
                    )
                if character_id is None:
                    continue
                for result in connection.execute(
                    "SELECT * FROM conversation_results WHERE task_id = ? ORDER BY attempt_no",
                    (row["task_id"],),
                ):
                    # 完整生成正文只随范围内的实际发言导出。
                    emitted = connection.execute(
                        "SELECT message_id FROM messages WHERE result_id = ?",
                        (result["result_id"],),
                    ).fetchone()
                    if emitted is not None and emitted[0] not in message_ids:
                        reference(
                            "conversation_result",
                            result["result_id"],
                            owner=character_id,
                            source_conversation=conversation_id,
                        )
                        continue
                    results.append(inspected_result(connection, result))
                    thought = connection.execute(
                        "SELECT * FROM thoughts WHERE result_id = ?",
                        (result["result_id"],),
                    ).fetchone()
                    if thought is not None:
                        thoughts.append(dict(thought))
            memory = []
            if character_id is not None:
                selected_segments = set()
                for row in connection.execute(
                    "SELECT m.*,s.first_sequence,s.last_sequence FROM memory_segments m "
                    "JOIN memory_segment_scenes s USING(segment_id) WHERE m.community_id=? "
                    "AND m.character_id=? AND s.conversation_id=? AND s.first_sequence<=? "
                    "AND s.last_sequence>=? ORDER BY m.position",
                    (community_id, character_id, conversation_id, through_sequence, first_sequence),
                ):
                    other_scenes = connection.execute(
                        "SELECT 1 FROM memory_segment_scenes WHERE segment_id=? AND "
                        "conversation_id!=?",
                        (row["segment_id"], conversation_id),
                    ).fetchone()
                    if (
                        row["first_sequence"] < first_sequence
                        or row["last_sequence"] > through_sequence
                        or other_scenes
                    ):
                        reference(
                            "memory_segment",
                            row["segment_id"],
                            row["source_version"],
                            character_id,
                            conversation_id,
                        )
                        continue
                    selected_segments.add(row["segment_id"])
                    memory.append(
                        self.memory.detail(
                            connection,
                            community_id,
                            character_id,
                            MemoryCollection.SEGMENTS,
                            row["segment_id"],
                        )
                    )
                selected_batches, selected_digests = set(), set()
                for row in connection.execute(
                    "SELECT * FROM memory_summary_batches WHERE community_id = ? "
                    "AND character_id = ? ORDER BY created_at_utc,batch_id",
                    (community_id, character_id),
                ):
                    batch = self.memory.batch(connection, row["batch_id"])
                    if not all(
                        source["segment_id"] in selected_segments for source in batch["sources"]
                    ):
                        continue
                    selected_batches.add(row["batch_id"])
                    digest = connection.execute(
                        "SELECT digest_id FROM memory_digests WHERE batch_id = ?",
                        (row["batch_id"],),
                    ).fetchone()
                    if digest is not None:
                        covered = {
                            item[0]
                            for item in connection.execute(
                                "SELECT segment_id FROM memory_digest_segments WHERE digest_id=?",
                                (digest[0],),
                            )
                        }
                        if (
                            set(batch["previous_digest_ids"]) <= selected_digests
                            and covered <= selected_segments
                        ):
                            selected_digests.add(digest[0])
                            memory.append(
                                self.memory.detail(
                                    connection,
                                    community_id,
                                    character_id,
                                    MemoryCollection.DIGESTS,
                                    digest[0],
                                )
                            )
                        else:
                            reference(
                                "conversation_digest",
                                digest[0],
                                owner=character_id,
                                source_conversation=conversation_id,
                            )
                    for previous in batch["previous_digest_ids"]:
                        if previous not in selected_digests:
                            reference(
                                "conversation_digest",
                                previous,
                                owner=character_id,
                                source_conversation=conversation_id,
                            )
                for collection, table in (
                    (MemoryCollection.FACTS, "memory_facts"),
                    (MemoryCollection.COGNITIONS, "memory_cognitions"),
                ):
                    for row in connection.execute(
                        f"SELECT memory_id,version,source_ref FROM {table} WHERE community_id=? "
                        "AND character_id=? AND source_kind='memory_summary_batch' "
                        "ORDER BY recorded_at_utc,memory_id,version",
                        (community_id, character_id),
                    ):
                        if row["source_ref"] not in selected_batches:
                            continue
                        entry = self.memory.detail(
                            connection,
                            community_id,
                            character_id,
                            collection,
                            row["memory_id"],
                            version=row["version"],
                        )
                        memory.append(entry)
                        for source in entry["sources"]:
                            reference(
                                source["source_kind"],
                                source["source_id"],
                                source["source_version"],
                                owner=character_id,
                                source_conversation=conversation_id,
                            )
            members = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM conversation_memberships WHERE community_id = ? "
                    "AND conversation_id = ? AND joined_after_sequence < ? "
                    "AND (left_at_sequence IS NULL OR left_at_sequence >= ?) "
                    "ORDER BY joined_at_utc,membership_id",
                    (community_id, conversation_id, through_sequence, first_sequence),
                )
            ]
            data = {
                "members": members,
                "messages": messages,
                "turns": turns,
                "tasks": tasks,
                "results": results,
                "thoughts": thoughts,
                "memory": memory,
                "references": list(references.values()),
            }
            return {
                "schema_version": 1,
                "scope": {
                    "community_id": community_id,
                    "conversation_id": conversation_id,
                    "character_id": character_id,
                    "first_sequence": first_sequence,
                    "through_sequence": through_sequence,
                },
                "exported_at_utc": datetime.now(UTC),
                "counts": {key: len(value) for key, value in data.items()},
                **data,
            }
