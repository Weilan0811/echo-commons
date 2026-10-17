import json
from typing import Literal

from echo_games.public import GameService

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.communities.game_participation_repository import (
    GameParticipationRepository,
)
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.shared.errors import InvalidCursor
from echo_commons.shared.management import (
    PageOptions,
    decode_page_cursor,
    encode_page_cursor,
    read_page,
)

GameRecordKind = Literal["events", "actions", "operations"]


class GameManagement:
    def __init__(self, database: Database, games: GameService) -> None:
        self.database = database
        self.games = games
        self.associations = GameParticipationRepository()
        self.conversations = ConversationRepository()

    def inspection(self, community_id: str, conversation_id: str) -> dict:
        with self.database.read() as connection:
            self.conversations.get(connection, community_id, conversation_id)
            game_id = self.associations.for_conversation(connection, community_id, conversation_id)
            return {
                "game": self.games.inspect_game(connection, game_id),
                "participations": self.games.inspect_participations(connection, game_id),
            }

    def records(
        self, community_id: str, conversation_id: str, kind: GameRecordKind, options: PageOptions
    ) -> dict:
        with self.database.read() as connection:
            self.conversations.get(connection, community_id, conversation_id)
            game_id = self.associations.for_conversation(connection, community_id, conversation_id)
            scope = {
                "query": "management_game_records",
                "community_id": community_id,
                "conversation_id": conversation_id,
                "game_id": game_id,
                "kind": kind,
            }
            if kind != "operations":
                boundary = (
                    decode_page_cursor(options.cursor, scope, 2) if options.cursor else (0, "")
                )
                if not isinstance(boundary[0], int) or not isinstance(boundary[1], str):
                    raise InvalidCursor("Invalid game record position")
                records = self.games.inspect_records(
                    connection,
                    game_id,
                    kind,
                    after=(boundary[0], boundary[1]),
                    limit=options.limit,
                )
                items = records[: options.limit]
                has_more = len(records) > options.limit
                return {
                    "items": items,
                    "cursor": encode_page_cursor(scope, (items[-1].position, items[-1].record_id))
                    if has_more
                    else None,
                    "has_more": has_more,
                }
            # 宿主回执包含结束活动；游戏包内部的生命周期回执通过公开方法读取。
            sql = (
                "SELECT json_array(requester_ref,request_id) AS record_id,"
                "COALESCE(json_extract(request_json,'$.expected_state_version'),0) AS position,"
                "result_json,request_json,operation,requester_ref "
                "FROM game_session_operations WHERE game_id=?"
            )
            page = read_page(
                connection,
                sql,
                (game_id,),
                scope=scope,
                order=("position", "record_id"),
                options=options,
            )
            items = []
            for row in page["items"]:
                document = json.loads(row["result_json"])
                request_id = document["game_request_id"]
                receipt = (
                    self.games.read_operation(connection, row["requester_ref"], game_id, request_id)
                    if request_id
                    else None
                )
                items.append(
                    {
                        "record_id": row["record_id"],
                        "position": receipt.state_version_after if receipt else row["position"],
                        "document": {
                            **document,
                            "operation": row["operation"],
                            "game_receipt": receipt.model_dump(mode="json") if receipt else None,
                        },
                        "command": json.loads(row["request_json"]),
                    }
                )
            page["items"] = items
            return page
