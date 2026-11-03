CREATE TABLE activity_scheduling (
    scheduler_id INTEGER PRIMARY KEY CHECK(scheduler_id=1),
    next_position INTEGER NOT NULL CHECK(next_position>=0)
);
INSERT INTO activity_scheduling VALUES (1,0);

UPDATE activity_results SET publication_status='silent'
    WHERE expression_status='silent' AND publication_status='pending';
