import base64
import binascii
import json
import sqlite3
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

T = TypeVar("T")


class ManagementModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class Page(ManagementModel, Generic[T]):
    items: list[T]
    cursor: str | None
    has_more: bool


class PageOptions(ManagementModel):
    cursor: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class PageCursor(ManagementModel):
    version: int = Field(default=1, ge=1, le=1)
    scope: dict[str, str | int | None]
    position: tuple[str | int, ...]


def read_page(
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple,
    *,
    scope: dict[str, str | int | None],
    order: tuple[str, ...],
    options: PageOptions,
) -> dict:
    boundary = ()
    clause = ""
    if options.cursor is not None:
        try:
            decoded = base64.b64decode(options.cursor, altchars=b"-_", validate=True)
            cursor = PageCursor.model_validate_json(decoded)
        except (ValueError, binascii.Error, ValidationError) as error:
            raise ValueError("Invalid management cursor") from error
        if cursor.scope != scope or len(cursor.position) != len(order):
            raise ValueError("Management cursor belongs to a different query")
        boundary = cursor.position
        columns = ",".join(order)
        slots = ",".join("?" for _ in order)
        clause = f" WHERE ({columns}) > ({slots})" if len(order) > 1 else (f" WHERE {columns} > ?")
    rows = connection.execute(
        f"SELECT * FROM ({sql}){clause} ORDER BY {','.join(order)} LIMIT ?",
        (*parameters, *boundary, options.limit + 1),
    ).fetchall()
    has_more = len(rows) > options.limit
    rows = rows[: options.limit]
    next_cursor = None
    if has_more:
        value = PageCursor(scope=scope, position=tuple(rows[-1][key] for key in order))
        next_cursor = base64.urlsafe_b64encode(value.model_dump_json().encode()).decode()
    return {"items": [dict(row) for row in rows], "cursor": next_cursor, "has_more": has_more}


def json_fields(row: sqlite3.Row | dict) -> dict:
    result = dict(row)
    for key in tuple(result):
        if key.endswith("_json"):
            value = result.pop(key)
            result[key.removesuffix("_json")] = json.loads(value) if value is not None else None
    return result
