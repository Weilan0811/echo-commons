-- 向量失败保存真实原因，重复扫描或重启不会反复花费调用额度。
CREATE TABLE memory_vector_failures (
    document_id INTEGER NOT NULL REFERENCES memory_search_documents(document_id) ON DELETE CASCADE,
    source_version TEXT NOT NULL,
    model_identity TEXT NOT NULL,
    error_code TEXT NOT NULL,
    provider_attempts INTEGER NOT NULL CHECK(provider_attempts >= 0),
    recorded_at_utc TEXT NOT NULL,
    PRIMARY KEY(document_id, source_version, model_identity)
);
