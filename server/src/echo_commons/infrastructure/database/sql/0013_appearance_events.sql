CREATE TEMP TABLE saved_event_sequence AS SELECT seq FROM sqlite_sequence WHERE name='realtime_events';
CREATE TABLE realtime_events_new (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    kind TEXT NOT NULL CHECK(kind IN (
        'conversation.message_created','conversation.turns_changed',
        'conversation.summary_changed','conversation.members_changed',
        'conversation.read_changed','community.status_changed',
        'community.appearance_changed','character.appearance_changed'
    )),
    object_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','turn','conversation','read','community','character')),
    source_id TEXT NOT NULL,
    audience_json TEXT NOT NULL CHECK(json_valid(audience_json) AND json_type(audience_json)='array'),
    created_at_utc TEXT NOT NULL
);
INSERT INTO realtime_events_new SELECT * FROM realtime_events;
DROP TABLE realtime_events;
ALTER TABLE realtime_events_new RENAME TO realtime_events;
UPDATE sqlite_sequence SET seq=MAX(seq,COALESCE((SELECT MAX(seq) FROM saved_event_sequence),0)) WHERE name='realtime_events';
INSERT INTO sqlite_sequence(name,seq) SELECT 'realtime_events',seq FROM saved_event_sequence WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='realtime_events');
DROP TABLE saved_event_sequence;
CREATE INDEX realtime_events_community_sequence ON realtime_events(community_id,sequence);
CREATE INDEX realtime_events_created ON realtime_events(created_at_utc);
