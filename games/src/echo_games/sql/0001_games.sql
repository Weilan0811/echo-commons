CREATE TABLE game_games (
    game_id TEXT PRIMARY KEY,
    game_type TEXT NOT NULL,
    ruleset_id TEXT NOT NULL,
    ruleset_version INTEGER NOT NULL CHECK(ruleset_version > 0),
    creator_ref TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('waiting','running','finished','cancelled')),
    state_version INTEGER NOT NULL CHECK(state_version > 0),
    document TEXT NOT NULL CHECK(json_valid(document))
);
CREATE INDEX game_games_listing ON game_games(game_type, status, game_id);

CREATE TABLE game_seats (
    game_id TEXT NOT NULL REFERENCES game_games(game_id),
    seat_id TEXT NOT NULL,
    PRIMARY KEY(game_id, seat_id)
);

CREATE TABLE game_participations (
    participation_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    seat_id TEXT NOT NULL,
    participant_ref TEXT NOT NULL,
    joined_state_version INTEGER NOT NULL CHECK(joined_state_version > 0),
    left_state_version INTEGER CHECK(left_state_version > joined_state_version),
    started_state_version INTEGER CHECK(started_state_version >= joined_state_version),
    document TEXT NOT NULL CHECK(json_valid(document)),
    FOREIGN KEY(game_id, seat_id) REFERENCES game_seats(game_id, seat_id),
    UNIQUE(game_id, seat_id, participation_id),
    UNIQUE(game_id, participation_id)
);
CREATE UNIQUE INDEX game_seat_current ON game_participations(game_id, seat_id)
    WHERE left_state_version IS NULL;
CREATE UNIQUE INDEX game_participant_current ON game_participations(game_id, participant_ref)
    WHERE left_state_version IS NULL;
CREATE INDEX game_participations_subject ON game_participations(participant_ref, game_id);

CREATE TABLE game_opportunities (
    opportunity_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    seat_id TEXT NOT NULL,
    participation_id TEXT NOT NULL,
    state_version INTEGER NOT NULL CHECK(state_version > 0),
    phase TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','consumed','expired')),
    FOREIGN KEY(game_id, seat_id, participation_id)
        REFERENCES game_participations(game_id, seat_id, participation_id)
);
CREATE UNIQUE INDEX game_opportunity_current ON game_opportunities(game_id, seat_id)
    WHERE status = 'open';

CREATE TABLE game_events (
    event_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES game_games(game_id),
    sequence INTEGER NOT NULL CHECK(sequence > 0),
    state_version INTEGER NOT NULL CHECK(state_version > 0),
    document TEXT NOT NULL CHECK(json_valid(document)),
    UNIQUE(game_id, sequence),
    UNIQUE(game_id, event_id)
);
CREATE TABLE game_event_audiences (
    game_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    participation_id TEXT NOT NULL,
    PRIMARY KEY(event_id, participation_id),
    FOREIGN KEY(game_id, event_id) REFERENCES game_events(game_id, event_id),
    FOREIGN KEY(game_id, participation_id) REFERENCES game_participations(game_id, participation_id)
);

CREATE TABLE game_operation_receipts (
    receipt_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL REFERENCES game_games(game_id),
    requester_ref TEXT NOT NULL,
    request_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('create','join','leave','start','resign','cancel')),
    command TEXT NOT NULL CHECK(json_valid(command)),
    document TEXT NOT NULL CHECK(json_valid(document)),
    UNIQUE(game_id, requester_ref, request_id)
);
CREATE UNIQUE INDEX game_creation_request ON game_operation_receipts(requester_ref, request_id)
    WHERE operation = 'create';

CREATE TABLE game_action_receipts (
    receipt_id TEXT PRIMARY KEY,
    game_id TEXT NOT NULL,
    seat_id TEXT NOT NULL,
    participant_ref TEXT NOT NULL,
    participation_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    opportunity_id TEXT NOT NULL REFERENCES game_opportunities(opportunity_id),
    command TEXT NOT NULL CHECK(json_valid(command)),
    document TEXT NOT NULL CHECK(json_valid(document)),
    FOREIGN KEY(game_id, seat_id, participation_id)
        REFERENCES game_participations(game_id, seat_id, participation_id),
    UNIQUE(game_id, seat_id, request_id)
);
