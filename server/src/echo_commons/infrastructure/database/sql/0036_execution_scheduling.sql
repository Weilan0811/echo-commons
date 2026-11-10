ALTER TABLE activity_scheduling RENAME TO execution_scheduling;
UPDATE execution_scheduling SET next_position=0 WHERE scheduler_id=1;
