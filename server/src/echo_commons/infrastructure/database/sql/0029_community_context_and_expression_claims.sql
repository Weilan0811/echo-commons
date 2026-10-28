ALTER TABLE communities ADD COLUMN world_description TEXT NOT NULL DEFAULT '';
ALTER TABLE communities ADD COLUMN community_rules TEXT NOT NULL DEFAULT '';

CREATE TABLE conversation_claims (
    result_id TEXT PRIMARY KEY REFERENCES conversation_results(result_id) ON DELETE CASCADE,
    output_contract TEXT NOT NULL,
    claims_json TEXT NOT NULL CHECK(json_valid(claims_json))
);
