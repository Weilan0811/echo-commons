DROP TABLE social_participation_judgments;
CREATE TABLE social_willingness_batches (
    social_turn_id TEXT PRIMARY KEY REFERENCES social_turns(social_turn_id),
    mode TEXT NOT NULL CHECK(mode IN ('remote_willingness','local_willingness')),
    configuration_json TEXT NOT NULL CHECK(json_valid(configuration_json)),
    status TEXT NOT NULL DEFAULT 'judging' CHECK(status IN ('judging','selected','quiet','failed')),
    selected_character_id TEXT,
    selection_json TEXT CHECK(selection_json IS NULL OR json_valid(selection_json))
);
CREATE TABLE social_willingness_tasks (
    task_id TEXT PRIMARY KEY REFERENCES conversation_tasks(task_id),
    social_turn_id TEXT NOT NULL REFERENCES social_willingness_batches(social_turn_id),
    request_json TEXT CHECK(request_json IS NULL OR json_valid(request_json)),
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    expression_selected INTEGER NOT NULL DEFAULT 0 CHECK(expression_selected IN (0,1))
);
