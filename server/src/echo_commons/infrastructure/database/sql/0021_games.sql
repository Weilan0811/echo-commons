CREATE TABLE community_games (
    game_id TEXT PRIMARY KEY REFERENCES game_games(game_id),
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(conversation_id)
);
CREATE INDEX community_games_listing ON community_games(community_id, game_id);
