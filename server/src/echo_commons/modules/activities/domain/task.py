from enum import StrEnum

from echo_games.public import GameViewPayload
from pydantic import TypeAdapter

VIEW_ADAPTER = TypeAdapter(GameViewPayload)


class ActivityMode(StrEnum):
    AUTOMATIC = "automatic"
    DECISION = "decision"
    ORDINARY = "ordinary"


def task_view(row):
    return VIEW_ADAPTER.validate_json(row["view_json"])
