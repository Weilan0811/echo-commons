ALTER TABLE reflection_node_tasks ADD COLUMN attempt_base_count INTEGER NOT NULL DEFAULT 0
    CHECK(attempt_base_count >= 0 AND attempt_base_count <= attempt_count);

-- 只补充从未获得正式记录的空初始状态。
UPDATE character_state_entries
SET value = CASE state_kind
    WHEN 'physical' THEN '无明显不适'
    WHEN 'mood' THEN '平和'
    WHEN 'activity' THEN '空闲'
END
WHERE source_kind = 'initialization' AND trim(value) = ''
AND NOT EXISTS (
    SELECT 1 FROM character_state_entries later
    WHERE later.character_id = character_state_entries.character_id
    AND later.state_kind = character_state_entries.state_kind
    AND later.state_version > character_state_entries.state_version
);
