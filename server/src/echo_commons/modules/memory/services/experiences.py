import json

from echo_commons.agents.contracts.context import MemoryItem
from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.memory.domain.sources import MemorySource, SourceKind
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.shared.actors import ActorRef


class MemoryExperiences:
    def __init__(self, activities):
        self.activities = activities

    def frames(self, connection, community, character, now):
        for participation in self.activities.observations.participation.participations(
            connection, community, ActorRef("character", character)
        ):
            if participation.joined_at_utc <= now:
                yield self.activities.read(
                    connection, community, character, participation.participation_id, now, limit=1
                )

    def sync(self, connection, community, character, now):
        for frame in self.frames(connection, community, character, now):
            connection.execute(
                "INSERT INTO memory_activity_episodes(participation_id,community_id,character_id,"
                "game_id,conversation_id,membership_id,game_type,joined_at_utc,closed_at_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(participation_id) DO UPDATE SET "
                "closed_at_utc=COALESCE(memory_activity_episodes.closed_at_utc,excluded.closed_at_utc)",
                (
                    frame.participation.participation_id,
                    community,
                    character,
                    frame.participation.game_id,
                    frame.boundary.conversation_id,
                    frame.boundary.membership_ids[0],
                    frame.game_type,
                    utc_text(frame.participation.joined_at_utc),
                    utc_text(frame.closed_at) if frame.closed_at else None,
                ),
            )

    def recent(self, connection, community, character, now):
        cards = []
        for frame in self.frames(connection, community, character, now):
            text = json.dumps(
                {
                    "游戏": frame.game_type,
                    "本人参与身份": frame.participation.participation_id,
                    "本人席位": frame.participation.seat_id,
                    "参与者": [
                        p.model_dump(mode="json") for p in frame.session_context.participants
                    ],
                    "状态": "活动已关闭" if frame.closed_at else frame.status,
                    "结果": frame.result,
                    "获胜者": [p.model_dump(mode="json") for p in frame.session_context.winners]
                    if frame.result is not None
                    else [],
                },
                ensure_ascii=False,
            )
            cards.append(
                MemoryItem(
                    memory_id=frame.participation.participation_id,
                    content_version=f"{frame.state_version}:{frame.closed_at}",
                    content=text,
                    source_kind="game_experience",
                    occurred_at_utc=frame.closed_at or frame.updated_at,
                    context_label="自身近期游戏经历",
                )
            )
        return tuple(sorted(cards, key=lambda card: card.occurred_at_utc, reverse=True))

    def freeze(
        self,
        connection,
        community,
        character,
        now,
        *,
        messages,
        thoughts,
        automatic,
        idle_seconds,
        max_materials,
        max_chars,
        message_ids=None,
    ):
        self.sync(connection, community, character, now)
        for episode in connection.execute(
            "SELECT * FROM memory_activity_episodes WHERE community_id=? AND character_id=? "
            "ORDER BY joined_at_utc,participation_id",
            (community, character),
        ).fetchall():
            frame = self.activities.read(
                connection,
                community,
                character,
                episode["participation_id"],
                now,
                after=episode["through_event_sequence"],
            )
            local = tuple(
                m
                for m in messages
                if m.conversation_id == frame.boundary.conversation_id
                and m.created_at_utc >= frame.participation.joined_at_utc
                and m.created_at_utc <= (frame.closed_at or now)
                and m.sequence <= frame.boundary.upper_sequence
            )
            if message_ids is not None:
                local = tuple(m for m in local if m.message_id in message_ids)
                if not local:
                    continue
            rows = connection.execute(
                "SELECT h.* FROM thoughts h JOIN activity_results r "
                "ON r.result_id=h.activity_result_id "
                "JOIN activity_tasks t USING(task_id) JOIN activity_inputs i USING(input_id) "
                "WHERE h.community_id=? AND h.character_id=? AND i.participation_id=? "
                "AND h.segment_id IS NULL AND h.content IS NOT NULL AND h.created_at_utc<=? "
                "ORDER BY h.created_at_utc,h.thought_id",
                (
                    community,
                    character,
                    episode["participation_id"],
                    utc_text(frame.closed_at or now),
                ),
            ).fetchall()
            groups = []
            for event in frame.events:
                content, _ = self.activities.content(connection, frame, event)
                groups.append((event.occurred_at_utc, "event", event, len(content)))
            for message in local:
                thought = thoughts.get(message.result_id)
                groups.append(
                    (
                        message.created_at_utc,
                        "message",
                        message,
                        len(message.text) + (len(thought["content"]) if thought else 0),
                    )
                )
            for thought in rows:
                groups.append(
                    (
                        utc_datetime(thought["created_at_utc"]),
                        "thought",
                        thought,
                        len(thought["content"]),
                    )
                )
            groups.sort(key=lambda item: item[0])
            if not groups:
                connection.execute(
                    "UPDATE memory_activity_episodes SET through_event_sequence=?,"
                    "materials_complete=? WHERE participation_id=?",
                    (
                        frame.through_sequence,
                        int(frame.closed_at is not None and not frame.has_more),
                        episode["participation_id"],
                    ),
                )
                continue
            total = sum(item[3] for item in groups)
            due = (
                not automatic
                or frame.closed_at is not None
                or frame.has_more
                or total >= max_chars
                or len(groups) >= max_materials
                or (now - groups[-1][0]).total_seconds() >= idle_seconds
            )
            if not due:
                continue
            sources, selected, times, size = [], [], [], 0
            last_event = episode["through_event_sequence"]
            for occurred, kind, value, chars in groups:
                count = 2 if kind == "message" and thoughts.get(value.result_id) else 1
                if sources and (size + chars > max_chars or len(sources) + count > max_materials):
                    break
                if chars > max_chars:
                    raise ValueError("One activity material exceeds the configured budget")
                if kind == "event":
                    sources.append(
                        MemorySource(
                            SourceKind.GAME_EVENT, value.event_id, str(value.state_version)
                        )
                    )
                    connection.execute(
                        "INSERT INTO memory_activity_event_refs VALUES (?,?,?,?,?,?) "
                        "ON CONFLICT(character_id,event_id) DO NOTHING",
                        (
                            community,
                            character,
                            value.event_id,
                            episode["participation_id"],
                            value.sequence,
                            str(value.state_version),
                        ),
                    )
                    last_event = value.sequence
                elif kind == "message":
                    selected.append(value)
                    sources.append(MemorySource(SourceKind.MESSAGE, value.message_id, "1"))
                    thought = thoughts.get(value.result_id)
                    if thought:
                        sources.append(
                            MemorySource(
                                SourceKind.THOUGHT,
                                thought["thought_id"],
                                thought["content_version"],
                            )
                        )
                else:
                    sources.append(
                        MemorySource(
                            SourceKind.THOUGHT, value["thought_id"], value["content_version"]
                        )
                    )
                times.append(occurred)
                size += chars
            consumed_all = len(times) == len(groups)
            connection.execute(
                "UPDATE memory_activity_episodes SET through_event_sequence=?,"
                "summary_digest_id=NULL,materials_complete=? WHERE participation_id=?",
                (
                    frame.through_sequence if consumed_all else last_event,
                    int(
                        consumed_all
                        and not frame.has_more
                        and frame.closed_at is not None
                        and message_ids is None
                    ),
                    episode["participation_id"],
                ),
            )
            return SegmentRepository().add(
                connection,
                community,
                character,
                tuple(selected),
                tuple(sources),
                (frame.boundary,),
                (),
                now,
                occurred_at=tuple(times),
                activity_participation_id=episode["participation_id"],
            )
        return None
