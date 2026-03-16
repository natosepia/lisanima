-- cre_tbl_t_rulebooks.sql
-- t_rulebooks テーブル定義

CREATE TABLE t_rulebooks (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    key         TEXT NOT NULL,
    content     TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    reason      TEXT,
    is_retired  BOOLEAN NOT NULL DEFAULT FALSE,
    persona_id  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(key, version)
);
