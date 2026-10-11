CREATE TABLE realtime_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    kind TEXT NOT NULL CHECK(kind IN (
        'conversation.message_created','conversation.turns_changed',
        'conversation.summary_changed','conversation.members_changed',
        'conversation.read_changed','community.status_changed'
    )),
    object_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','turn','conversation','read','community')),
    source_id TEXT NOT NULL,
    audience_json TEXT NOT NULL CHECK(json_valid(audience_json) AND json_type(audience_json)='array'),
    created_at_utc TEXT NOT NULL
);
CREATE INDEX realtime_events_community_sequence ON realtime_events(community_id,sequence);
CREATE INDEX realtime_events_created ON realtime_events(created_at_utc);
CREATE TABLE realtime_event_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    cleaned_through INTEGER NOT NULL CHECK(cleaned_through>=0)
);
INSERT INTO realtime_event_state VALUES (1,0);
