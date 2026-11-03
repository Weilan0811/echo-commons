import json
import sqlite3

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.execution_records import ExecutionRecordRepository
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.inspection import redact_thoughts
from echo_commons.shared.management import PageOptions, json_fields, read_page


def message_detail(connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
    message = MessageRepository().from_row(connection, row)
    return {
        "message_id": message.message_id,
        "community_id": message.community_id,
        "conversation_id": message.conversation_id,
        "sequence": message.sequence,
        "sender": message.sender,
        "text": message.text,
        "visibility": message.visibility,
        "mentions": message.mentions,
        "reply_to_message_id": message.reply_to_message_id,
        "source_turn_id": message.source_turn_id,
        "result_id": message.result_id,
        "activity_result_id": message.activity_result_id,
        "trace_id": message.trace_id,
        "created_at_utc": message.created_at_utc,
        "audience": [
            dict(item)
            for item in connection.execute(
                "SELECT cm.membership_id,cm.actor_kind,cm.actor_id FROM message_recipients mr "
                "JOIN conversation_memberships cm ON cm.membership_id = mr.membership_id "
                "WHERE mr.message_id = ? ORDER BY cm.membership_id",
                (message.message_id,),
            )
        ],
    }


def inspected_result(
    connection: sqlite3.Connection, row: sqlite3.Row, *, include_claims: bool = False
) -> dict:
    result = json_fields(row)
    thought = connection.execute(
        "SELECT content,content_removed_at_utc FROM thoughts WHERE result_id = ?",
        (row["result_id"],),
    ).fetchone()
    removed = thought["content_removed_at_utc"] if thought is not None else None
    result["thought_removed_at_utc"] = removed
    if include_claims:
        private = connection.execute(
            "SELECT output_contract,claims_json FROM conversation_claims WHERE result_id=?",
            (row["result_id"],),
        ).fetchone()
        result["private_claims"] = json.loads(private["claims_json"]) if private else None
        result["agent_output_contract"] = (
            private["output_contract"] if private else row["output_contract"]
        )
    output = result["payload"].get("output")
    if thought is not None and output is not None:
        output["payload"]["thought"] = thought["content"] if removed is None else None
    return result


class ConversationManagement:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.conversations = ConversationRepository()
        self.tasks = ConversationTaskRepository()

    def conversation(self, community_id: str, conversation_id: str):
        with self.database.read() as connection:
            return self.conversations.get(connection, community_id, conversation_id)

    def conversations_for(self, community_id, options, *, kind=None, status=None):
        with self.database.read() as connection:
            CommunityRepository().get(connection, community_id)
            sql = "SELECT * FROM conversations WHERE community_id=?"
            parameters = [community_id]
            for key, value in (("kind", kind), ("status", status)):
                if value is not None:
                    sql += f" AND {key}=?"
                    parameters.append(value)
            return read_page(
                connection,
                sql,
                tuple(parameters),
                scope={
                    "query": "management_conversations",
                    "community_id": community_id,
                    "kind": kind,
                    "status": status,
                },
                order=("created_at_utc", "conversation_id"),
                options=options,
            )

    def members(self, community_id: str, conversation_id: str, options: PageOptions) -> dict:
        with self.database.read() as connection:
            self.conversations.get(connection, community_id, conversation_id)
            return read_page(
                connection,
                "SELECT * FROM conversation_memberships WHERE community_id = ? "
                "AND conversation_id = ?",
                (community_id, conversation_id),
                scope={
                    "query": "conversation_members",
                    "community_id": community_id,
                    "conversation_id": conversation_id,
                },
                order=("joined_at_utc", "membership_id"),
                options=options,
            )

    def messages(self, community_id: str, conversation_id: str, options: PageOptions) -> dict:
        with self.database.read() as connection:
            self.conversations.get(connection, community_id, conversation_id)
            return read_page(
                connection,
                "SELECT message_id,community_id,conversation_id,sequence,"
                "sender_kind,sender_id,visibility,substr(text,1,160) AS text_preview,"
                "source_turn_id,result_id,trace_id,created_at_utc FROM messages "
                "WHERE community_id = ? AND conversation_id = ?",
                (community_id, conversation_id),
                scope={
                    "query": "messages",
                    "community_id": community_id,
                    "conversation_id": conversation_id,
                },
                order=("sequence",),
                options=options,
            )

    def message(self, community_id: str, conversation_id: str, message_id: str) -> dict:
        with self.database.read() as connection:
            self.conversations.get(connection, community_id, conversation_id)
            row = connection.execute(
                "SELECT * FROM messages WHERE community_id = ? AND conversation_id = ? "
                "AND message_id = ?",
                (community_id, conversation_id, message_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Message does not exist in this conversation")
            return message_detail(connection, row)

    def turns(self, community_id: str, conversation_id: str, options: PageOptions) -> dict:
        with self.database.read() as connection:
            self.conversations.get(connection, community_id, conversation_id)
            page = read_page(
                connection,
                "SELECT * FROM social_turns WHERE community_id = ? AND conversation_id = ?",
                (community_id, conversation_id),
                scope={
                    "query": "turns",
                    "community_id": community_id,
                    "conversation_id": conversation_id,
                },
                order=("created_at_utc", "social_turn_id"),
                options=options,
            )
            page["items"] = [json_fields(row) for row in page["items"]]
            return page

    def turn(self, community_id: str, conversation_id: str, turn_id: str) -> dict:
        with self.database.read() as connection:
            self.conversations.get(connection, community_id, conversation_id)
            row = connection.execute(
                "SELECT * FROM social_turns WHERE community_id = ? AND conversation_id = ? "
                "AND social_turn_id = ?",
                (community_id, conversation_id, turn_id),
            ).fetchone()
            if row is None:
                raise NotFoundError("Social turn does not exist in this conversation")
            return {
                **json_fields(row),
                "chain": dict(chain)
                if (
                    chain := connection.execute(
                        "SELECT * FROM social_chains WHERE chain_id=?",
                        (row["chain_id"],),
                    ).fetchone()
                )
                else None,
                "observations": [
                    dict(item)
                    for item in connection.execute(
                        "SELECT * FROM social_observations WHERE chain_id=? ORDER BY membership_id",
                        (row["chain_id"],),
                    )
                ],
                "participation": [
                    dict(item)
                    for item in connection.execute(
                        "SELECT * FROM participation_decisions WHERE social_turn_id = ? "
                        "ORDER BY character_id",
                        (turn_id,),
                    )
                ],
                "task_ids": [
                    item[0]
                    for item in connection.execute(
                        "SELECT task_id FROM conversation_tasks WHERE social_turn_id = ? "
                        "ORDER BY character_id",
                        (turn_id,),
                    )
                ],
                "activity_sources": [
                    dict(item)
                    for item in connection.execute(
                        "SELECT a.source_id,a.task_id,a.character_id,a.status,"
                        "a.observation_max_sequence,t.purpose FROM activity_task_sources a "
                        "LEFT JOIN activity_tasks t USING(task_id) "
                        "WHERE a.social_turn_id=? ORDER BY a.created_at_utc,a.source_id",
                        (turn_id,),
                    )
                ],
                "input_message_ids": [
                    item[0]
                    for item in connection.execute(
                        "SELECT bm.message_id FROM social_turn_batches tb "
                        "JOIN input_batch_messages bm ON bm.input_batch_id = tb.input_batch_id "
                        "JOIN messages m ON m.message_id = bm.message_id "
                        "WHERE tb.social_turn_id = ? ORDER BY tb.ordinal,m.sequence",
                        (turn_id,),
                    )
                ],
            }

    def task_list(
        self,
        community_id: str,
        options: PageOptions,
        *,
        conversation_id: str | None = None,
        character_id: str | None = None,
        status: str | None = None,
    ) -> dict:
        with self.database.read() as connection:
            CommunityRepository().get(connection, community_id)
            if conversation_id is not None:
                self.conversations.get(connection, community_id, conversation_id)
            if character_id is not None:
                InstanceRepository().get(connection, community_id, character_id)
            conditions, parameters = ["t.community_id = ?"], [community_id]
            for key, value in (
                ("conversation_id", conversation_id),
                ("character_id", character_id),
                ("status", status),
            ):
                if value is not None:
                    conditions.append(f"t.{key} = ?")
                    parameters.append(value)
            page = read_page(
                connection,
                "SELECT t.task_id,t.community_id,t.conversation_id,t.social_turn_id,"
                "s.initiation_id,"
                "t.character_id,t.status,t.attempt_count,t.lease_generation,t.last_error_code,"
                "t.trace_id,t.created_at_utc,t.updated_at_utc FROM conversation_tasks t "
                "JOIN social_turns s USING(social_turn_id) WHERE " + " AND ".join(conditions),
                tuple(parameters),
                scope={
                    "query": "tasks",
                    "community_id": community_id,
                    "conversation_id": conversation_id,
                    "character_id": character_id,
                    "status": status,
                },
                order=("created_at_utc", "task_id"),
                options=options,
            )

            records = ExecutionRecordRepository()
            for item in page["items"]:
                item.update(
                    records.summary(
                        connection, "conversation_reply", item["task_id"], item["status"]
                    )
                )
            return page

    def task(
        self,
        community_id: str,
        character_id: str,
        task_id: str,
        options: PageOptions | None = None,
    ) -> dict:
        options = options or PageOptions()
        with self.database.read() as connection:
            row = self.tasks.get(connection, task_id)
            if (row["community_id"], row["character_id"]) != (community_id, character_id):
                raise NotFoundError("Task does not exist in this character scope")
            summary = dict(row)
            summary.pop("snapshot_json")
            participation = connection.execute(
                "SELECT * FROM social_participation_judgments WHERE task_id=?", (task_id,)
            ).fetchone()
            judgment = None
            if participation is not None:
                request = json.loads(participation["request_json"] or "{}")
                response = json.loads(participation["response_json"] or "{}")
                judgment = dict(
                    mode=participation["mode"],
                    choice=participation["choice"],
                    model_profile=request.get("model_profile"),
                    model_entry_id=request.get("model_entry_id"),
                    model=response.get("model"),
                    probabilities=response.get("answers", {})
                    .get("participation", {})
                    .get("probabilities"),
                    latency_ms=response.get("latency_ms"),
                    decided_at_utc=participation["decided_at_utc"],
                )
            initiation = None
            if row["initiation_id"] is not None:
                initiation = json_fields(
                    connection.execute(
                        "SELECT * FROM conversation_initiations WHERE initiation_id=?",
                        (row["initiation_id"],),
                    ).fetchone()
                )
            records = ExecutionRecordRepository()
            summary.update(
                records.summary(connection, "conversation_reply", task_id, row["status"])
            )
            return {
                "task": summary,
                "initiation": initiation,
                "participation": judgment,
                "recovery_history": records.history(
                    connection, "conversation_reply", task_id, community_id, character_id, options
                ),
                "context": redact_thoughts(
                    connection,
                    community_id,
                    character_id,
                    self.tasks.snapshot(connection, task_id).model_dump(mode="json"),
                )
                if row["snapshot_json"] is not None
                else None,
                "results": [
                    inspected_result(connection, item, include_claims=True)
                    for item in connection.execute(
                        "SELECT * FROM conversation_results WHERE task_id = ? ORDER BY attempt_no",
                        (task_id,),
                    )
                ],
            }
