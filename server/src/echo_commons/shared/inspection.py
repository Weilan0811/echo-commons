import sqlite3


def redact_thoughts(
    connection: sqlite3.Connection,
    community_id: str,
    character_id: str,
    snapshot: dict,
) -> dict:
    # 诊断投影过滤已经清除的正文，恢复执行仍使用原冻结输入。
    sources = [
        (item, "thought_id") for item in snapshot.get("memory", {}).get("history_thoughts", [])
    ]
    sources.extend(
        (item, "source_id") for item in snapshot.get("materials", []) if item["kind"] == "thought"
    )
    for item, identity in sources:
        row = connection.execute(
            "SELECT content_removed_at_utc FROM thoughts WHERE community_id = ? "
            "AND character_id = ? AND thought_id = ?",
            (community_id, character_id, item[identity]),
        ).fetchone()
        if row is not None and row[0] is not None:
            item["content"] = None
            item["content_removed_at_utc"] = row[0]
    return snapshot
