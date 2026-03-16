-- cre_tbl_t_messages.sql
-- t_messages テーブル定義

CREATE TABLE t_messages (
    id             INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id     INTEGER NOT NULL REFERENCES t_sessions(id) ON DELETE CASCADE,
    speaker        TEXT NOT NULL,
    target         TEXT,
    content        TEXT NOT NULL,
    joy            SMALLINT NOT NULL DEFAULT 0,
    anger          SMALLINT NOT NULL DEFAULT 0,
    sorrow         SMALLINT NOT NULL DEFAULT 0,
    fun            SMALLINT NOT NULL DEFAULT 0,
    emotion_total  SMALLINT GENERATED ALWAYS AS (
        joy + anger + sorrow + fun
    ) STORED,
    source         TEXT,
    is_deleted     BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_reason TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
