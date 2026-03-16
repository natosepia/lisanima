-- cre_tbl_t_sessions.sql
-- t_sessions テーブル定義

CREATE TABLE t_sessions (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    persona_id  TEXT NOT NULL DEFAULT 'lisa',
    date        DATE NOT NULL,
    session_seq INTEGER NOT NULL DEFAULT 1,
    project     TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at    TIMESTAMPTZ,
    UNIQUE(persona_id, date, session_seq)
);
