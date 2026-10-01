-- Rebuildable sparse memory search projection.
--
-- The source tables remain authoritative.  ``memory_search_documents`` keeps
-- a stable source-to-row mapping so a later vector projection can use the
-- same document id and content version.  The FTS table stores only the
-- jieba-pre-tokenized search text and a bounded display copy.
CREATE TABLE IF NOT EXISTS memory_search_documents (
    document_id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    conversation_id TEXT,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('memory_entry', 'message')),
    source_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    occurred_at_utc TEXT,
    searchable INTEGER NOT NULL DEFAULT 1 CHECK(searchable IN (0, 1)),
    updated_at_utc TEXT NOT NULL,
    UNIQUE(account_id, character_id, source_kind, source_id)
);

CREATE INDEX IF NOT EXISTS ix_memory_search_documents_scope
ON memory_search_documents(account_id, character_id, searchable, source_kind);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_search_fts USING fts5(
    tokenized_text,
    display_text UNINDEXED
);
